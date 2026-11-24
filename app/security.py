"""Cryptographic primitives: password hashing, tokens, IP pseudonymisation.

Everything secret-handling goes through this module so the parameters live in
one place and can be raised later without hunting through routes.
"""

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type

from app.config import settings

# Argon2id. Memory cost dominates GPU attack economics, so it is the knob
# worth spending on; 64 MiB per hash is comfortable on a small VPS as long as
# login is rate limited.
_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

# A 4-digit share PIN has ~13 bits of entropy. Hashing cannot fix that; only
# rate limiting can. The cost here is raised anyway so that a database leak
# does not hand over every PIN in a single pass.
_pin_hasher = PasswordHasher(
    time_cost=4,
    memory_cost=96 * 1024,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

# A precomputed hash of a random string. Verified against on failed lookups so
# that "user does not exist" and "wrong password" take the same wall time and
# the login form cannot be used to enumerate accounts.
_DUMMY_HASH = _password_hasher.hash(secrets.token_hex(32))


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> tuple[bool, str | None]:
    """Verify a password in constant-ish time.

    Returns (ok, new_hash). new_hash is set when the stored hash used weaker
    parameters than the current policy, so callers can transparently upgrade
    it on a successful login.
    """
    if stored_hash is None:
        # Burn the same amount of time we would have spent on a real verify.
        try:
            _password_hasher.verify(_DUMMY_HASH, password)
        except (VerifyMismatchError, InvalidHashError):
            pass
        return False, None

    try:
        _password_hasher.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False, None

    if _password_hasher.check_needs_rehash(stored_hash):
        return True, _password_hasher.hash(password)
    return True, None


def hash_pin(pin: str) -> str:
    return _pin_hasher.hash(pin)


def verify_pin(pin: str, stored_hash: str) -> bool:
    try:
        _pin_hasher.verify(stored_hash, pin)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def generate_token(n_bytes: int = 32) -> str:
    """A URL-safe secret. 32 bytes is 256 bits: unguessable, not enumerable."""
    return secrets.token_urlsafe(n_bytes)


def hash_token(token: str) -> str:
    """Keyed hash of a bearer token.

    Tokens are high-entropy, so a fast keyed hash is enough and lets lookups
    be a single indexed query. The key means a leaked database alone does not
    yield working links.
    """
    return hmac.new(
        settings.secret_key.encode(), token.encode(), hashlib.sha256
    ).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def hash_ip(ip: str | None) -> str | None:
    """Pseudonymise a client IP for the audit and access logs.

    Raw IPs are personal data and we have no use for them beyond "was this the
    same visitor". A salted hash answers that and nothing else.
    """
    if not ip:
        return None
    return hashlib.sha256((settings.ip_hash_salt + ip).encode()).hexdigest()[:32]


def password_problems(password: str) -> list[str]:
    """Length-first policy.

    No composition rules: forcing a symbol produces Passw0rd! and nothing
    else. Length plus a breach check is what actually helps.
    """
    problems: list[str] = []
    if len(password) < settings.min_password_length:
        problems.append(
            f"La contraseña debe tener al menos {settings.min_password_length} caracteres."
        )
    if password.lower() in {"contrasena", "password", "12345678", "bitamed"}:
        problems.append("Esa contraseña es demasiado común.")
    return problems
