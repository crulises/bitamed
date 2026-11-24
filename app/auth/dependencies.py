"""FastAPI dependencies: who is asking, and may they.

Usage in a route:

    @router.post("/logbooks/{logbook_id}/documents")
    async def upload(
        access: Annotated[AccessContext, Depends(require(Permission.UPLOAD_DOCUMENT))],
    ): ...

The route says what capability it needs. It does not look at roles, and it
does not look at logbook status. Both are handled here, once.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, record
from app.auth.permissions import AccessContext, Permission
from app.auth.sessions import SessionData, load_session
from app.config import settings
from app.db import get_db
from app.models.enums import UserStatus
from app.models.identity import UserAccount
from app.models.logbook import Logbook, Membership
from app.security import constant_time_equals, hash_ip


def client_ip_hash(request: Request) -> str | None:
    # X-Forwarded-For is only trusted because uvicorn runs with
    # --proxy-headers behind our own reverse proxy.
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (
        request.client.host if request.client else None
    )
    return hash_ip(ip)


async def get_session_data(request: Request) -> SessionData | None:
    raw_sid = request.cookies.get(settings.session_cookie_name)
    if not raw_sid:
        return None
    return await load_session(raw_sid)


async def get_current_user_optional(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserAccount | None:
    session = await get_session_data(request)
    if session is None:
        return None

    user = await db.get(UserAccount, session.user_id)
    if user is None or not user.can_log_in:
        # Status is re-checked on every request rather than trusted from the
        # session, so suspending an account takes effect immediately.
        return None

    request.state.session = session
    request.state.user = user
    return user


async def get_current_user(
    user: Annotated[UserAccount | None, Depends(get_current_user_optional)],
) -> UserAccount:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Necesitás iniciar sesión.",
            headers={"HX-Redirect": "/login"},
        )
    return user


async def require_instance_admin(
    user: Annotated[UserAccount, Depends(get_current_user)],
) -> UserAccount:
    """Server administration only.

    Being an instance admin does not grant access to any logbook's contents.
    Approving signups and reading someone's medical record are different
    powers and this codebase keeps them apart.
    """
    if not user.is_instance_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tenés permisos de administración.")
    return user


async def get_access_context(
    logbook_id: Annotated[uuid.UUID, Path()],
    user: Annotated[UserAccount, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccessContext:
    """Resolve the caller's standing on one logbook, once per request."""
    row = (
        await db.execute(
            select(Membership.role, Logbook.status)
            .join(Logbook, Logbook.id == Membership.logbook_id)
            .where(
                Membership.logbook_id == logbook_id,
                Membership.user_id == user.id,
                Membership.joined_at.is_not(None),
            )
        )
    ).first()

    if row is None:
        # 404, not 403. Telling a stranger that a logbook exists is itself a
        # disclosure: the set of people someone keeps records for is private.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontrada.")

    role, logbook_status = row
    return AccessContext(
        user_id=user.id,
        logbook_id=logbook_id,
        role=role,
        logbook_status=logbook_status,
    )


def require(*permissions: Permission) -> Callable:
    """Dependency factory. All listed permissions must be granted."""

    async def _dep(
        request: Request,
        access: Annotated[AccessContext, Depends(get_access_context)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> AccessContext:
        missing = [p for p in permissions if not access.can(p)]
        if missing:
            await record(
                db,
                action=AuditAction.PERMISSION_DENIED,
                actor_id=access.user_id,  # type: ignore[arg-type]
                logbook_id=access.logbook_id,  # type: ignore[arg-type]
                detail={"required": [p.value for p in missing], "role": access.role.value},
                ip_hash=client_ip_hash(request),
            )
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, access.why_denied(missing[0])
            )
        return access

    return _dep


async def verify_csrf(request: Request) -> None:
    """Double-submit CSRF check on every unsafe method.

    Session cookies are SameSite=Lax, which covers most of this already, but
    Lax still permits top-level POST navigations in some browsers, and this
    costs one header.
    """
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return

    session: SessionData | None = getattr(request.state, "session", None)
    if session is None:
        session = await get_session_data(request)
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión expirada.")

    submitted = request.headers.get("x-csrf-token")
    if not submitted:
        form = await request.form()
        submitted = str(form.get("csrf_token", ""))

    if not submitted or not constant_time_equals(submitted, session.csrf_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Token CSRF inválido.")


CurrentUser = Annotated[UserAccount, Depends(get_current_user)]
OptionalUser = Annotated[UserAccount | None, Depends(get_current_user_optional)]
InstanceAdmin = Annotated[UserAccount, Depends(require_instance_admin)]
Db = Annotated[AsyncSession, Depends(get_db)]
CsrfChecked = Annotated[None, Depends(verify_csrf)]


def _unused() -> None:  # pragma: no cover
    _ = UserStatus
