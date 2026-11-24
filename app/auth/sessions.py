"""Server-side sessions, stored in Redis.

Deliberately not JWT. For health data, revocation has to be real: logging out
must actually log out, and suspending an account must kill its live sessions
immediately. A JWT can only approximate that with a denylist, which is a
session store with extra steps and worse failure modes.

Layout:
    session:<sid>        hash of session data, TTL = idle timeout
    user_sessions:<uid>  set of that user's session ids, for bulk revocation
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import redis.asyncio as aioredis

from app.config import settings
from app.security import generate_token, hash_token

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def _session_key(sid_hash: str) -> str:
    return f"session:{sid_hash}"


def _user_key(user_id: uuid.UUID) -> str:
    return f"user_sessions:{user_id}"


@dataclass(slots=True)
class SessionData:
    user_id: uuid.UUID
    created_at: datetime
    csrf_token: str
    ip_hash: str | None = None
    user_agent: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "user_id": str(self.user_id),
                "created_at": self.created_at.isoformat(),
                "csrf_token": self.csrf_token,
                "ip_hash": self.ip_hash,
                "user_agent": self.user_agent,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> SessionData:
        d = json.loads(raw)
        return cls(
            user_id=uuid.UUID(d["user_id"]),
            created_at=datetime.fromisoformat(d["created_at"]),
            csrf_token=d["csrf_token"],
            ip_hash=d.get("ip_hash"),
            user_agent=d.get("user_agent"),
        )


async def create_session(
    user_id: uuid.UUID,
    ip_hash: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, SessionData]:
    """Returns (raw_session_id_for_cookie, data).

    Only the hash of the session id is stored, so a dump of Redis does not
    hand over usable cookies.
    """
    raw_sid = generate_token(32)
    sid_hash = hash_token(raw_sid)
    data = SessionData(
        user_id=user_id,
        created_at=datetime.now(UTC),
        csrf_token=generate_token(24),
        ip_hash=ip_hash,
        user_agent=user_agent,
    )
    r = get_redis()
    pipe = r.pipeline()
    pipe.set(_session_key(sid_hash), data.to_json(), ex=settings.session_idle_seconds)
    pipe.sadd(_user_key(user_id), sid_hash)
    pipe.expire(_user_key(user_id), settings.session_max_age_seconds)
    await pipe.execute()
    return raw_sid, data


async def load_session(raw_sid: str) -> SessionData | None:
    """Loads a session and slides the idle window.

    The absolute lifetime is enforced separately: a session that keeps being
    used still dies at session_max_age_seconds, so a permanently-open tab
    cannot become a permanent credential.
    """
    sid_hash = hash_token(raw_sid)
    r = get_redis()
    raw = await r.get(_session_key(sid_hash))
    if raw is None:
        return None

    data = SessionData.from_json(raw)
    age = (datetime.now(UTC) - data.created_at).total_seconds()
    if age > settings.session_max_age_seconds:
        await destroy_session(raw_sid)
        return None

    await r.expire(_session_key(sid_hash), settings.session_idle_seconds)
    return data


async def destroy_session(raw_sid: str) -> None:
    sid_hash = hash_token(raw_sid)
    r = get_redis()
    raw = await r.get(_session_key(sid_hash))
    await r.delete(_session_key(sid_hash))
    if raw:
        data = SessionData.from_json(raw)
        await r.srem(_user_key(data.user_id), sid_hash)


async def destroy_all_sessions(user_id: uuid.UUID) -> int:
    """Kill every session of a user.

    Called on suspension, on password change, and from the "cerrar sesión en
    todos los dispositivos" button. This is the capability JWTs give up.
    """
    r = get_redis()
    sid_hashes = await r.smembers(_user_key(user_id))
    if not sid_hashes:
        return 0
    pipe = r.pipeline()
    for h in sid_hashes:
        pipe.delete(_session_key(h))
    pipe.delete(_user_key(user_id))
    await pipe.execute()
    return len(sid_hashes)


# -----------------------------------------------------------------------------
# Login throttling
# -----------------------------------------------------------------------------


async def register_failed_login(identifier: str) -> int:
    """Counts failures per identifier (email or IP hash). Returns the count."""
    r = get_redis()
    key = f"login_fail:{identifier}"
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, settings.login_lockout_minutes * 60)
    return int(count)


async def is_login_locked(identifier: str) -> bool:
    r = get_redis()
    count = await r.get(f"login_fail:{identifier}")
    return count is not None and int(count) >= settings.login_max_attempts


async def clear_failed_logins(identifier: str) -> None:
    await get_redis().delete(f"login_fail:{identifier}")
