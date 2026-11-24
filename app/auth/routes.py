"""Authentication routes: registration, approval, login, logout, password.

Registration is closed by default: a signup creates a RegistrationRequest, an
instance admin approves it, and only then does a UserAccount exist. Opening
the instance to the public is a config flag, not a code change.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from sqlalchemy import select

from app.audit import AuditAction, record
from app.auth.dependencies import (
    CsrfChecked,
    CurrentUser,
    Db,
    InstanceAdmin,
    client_ip_hash,
)
from app.auth.sessions import (
    clear_failed_logins,
    create_session,
    destroy_all_sessions,
    destroy_session,
    is_login_locked,
    register_failed_login,
)
from app.config import settings
from app.models.enums import LegalKind, UserStatus
from app.models.identity import (
    LegalDocument,
    RegistrationRequest,
    TermsAcceptance,
    UserAccount,
)
from app.security import hash_password, password_problems, verify_password

router = APIRouter(tags=["auth"])


def _set_session_cookie(response: Response, raw_sid: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        raw_sid,
        max_age=settings.session_max_age_seconds,
        httponly=True,                    # no JS access, ever
        secure=settings.is_production,    # HTTPS only outside dev
        samesite="lax",
        path="/",
    )


async def _current_legal(db, kind: LegalKind, lang: str) -> LegalDocument:
    """Latest effective version of a legal text, falling back to Spanish."""
    stmt = (
        select(LegalDocument)
        .where(
            LegalDocument.kind == kind,
            LegalDocument.lang == lang,
            LegalDocument.effective_from <= datetime.now(UTC),
        )
        .order_by(LegalDocument.effective_from.desc())
        .limit(1)
    )
    doc = (await db.execute(stmt)).scalar_one_or_none()
    if doc is None and lang != "es":
        return await _current_legal(db, kind, "es")
    if doc is None:
        raise HTTPException(500, "No hay términos publicados. Cargá la versión inicial.")
    return doc


# -----------------------------------------------------------------------------
# Registration
# -----------------------------------------------------------------------------


@router.post("/register")
async def register(
    request: Request,
    db: Db,
    email: Annotated[str, Form()],
    display_name: Annotated[str, Form()],
    password: Annotated[str, Form()],
    accept_terms: Annotated[bool, Form()] = False,
    note: Annotated[str, Form()] = "",
    locale: Annotated[str, Form()] = "es",
) -> dict:
    if not accept_terms:
        raise HTTPException(400, "Tenés que aceptar los términos y el aviso de privacidad.")

    problems = password_problems(password)
    if problems:
        raise HTTPException(400, " ".join(problems))

    email = email.strip().lower()
    terms = await _current_legal(db, LegalKind.TERMS, locale)
    ip = client_ip_hash(request)

    existing = (
        await db.execute(select(UserAccount).where(UserAccount.email == email))
    ).scalar_one_or_none()

    # Same response either way. A signup form that says "ese email ya existe"
    # is an account enumeration oracle, and here the accounts belong to people
    # who keep medical records.
    generic = {
        "status": "pending",
        "message": "Recibimos tu solicitud. Te avisamos por correo cuando esté aprobada.",
    }
    if existing is not None:
        return generic

    if settings.allow_open_registration:
        user = UserAccount(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name.strip(),
            locale=locale,
            timezone=settings.default_timezone,
            status=UserStatus.ACTIVE,
            is_instance_admin=False,
        )
        db.add(user)
        await db.flush()
        db.add(
            TermsAcceptance(
                user_id=user.id,
                legal_document_id=terms.id,
                ip_hash=ip,
                user_agent=request.headers.get("user-agent"),
            )
        )
        await record(
            db, action=AuditAction.USER_REGISTERED, actor_id=user.id,
            entity_type="user_account", entity_id=user.id, ip_hash=ip,
        )
        return {"status": "active", "message": "Cuenta creada."}

    # Closed instance: park the request until an admin approves it. The
    # password hash rides along so approval does not need a second round trip.
    db.add(
        RegistrationRequest(
            email=email,
            display_name=display_name.strip(),
            note=(
                f"{note.strip()}\n[pwhash:{hash_password(password)}]"
                f"\n[locale:{locale}][terms:{terms.id}][ip:{ip}]"
            ),
        )
    )
    return generic


@router.get("/admin/registrations")
async def list_registrations(admin: InstanceAdmin, db: Db) -> list[dict]:
    rows = (
        await db.execute(
            select(RegistrationRequest)
            .where(RegistrationRequest.reviewed_at.is_(None))
            .order_by(RegistrationRequest.requested_at)
        )
    ).scalars()
    return [
        {
            "id": str(r.id),
            "email": r.email,
            "display_name": r.display_name,
            "requested_at": r.requested_at.isoformat(),
            # The stashed password hash is never echoed back.
            "note": (r.note or "").split("\n[pwhash:")[0],
        }
        for r in rows
    ]


@router.post("/admin/registrations/{request_id}/approve")
async def approve_registration(
    request: Request,
    request_id: uuid.UUID,
    admin: InstanceAdmin,
    db: Db,
    _csrf: CsrfChecked = None,
) -> dict:
    req = await db.get(RegistrationRequest, request_id)
    if req is None or req.reviewed_at is not None:
        raise HTTPException(404, "Solicitud no encontrada o ya revisada.")

    note = req.note or ""
    try:
        pwhash = note.split("[pwhash:")[1].split("]")[0]
        locale = note.split("[locale:")[1].split("]")[0]
        terms_id = uuid.UUID(note.split("[terms:")[1].split("]")[0])
    except (IndexError, ValueError):
        raise HTTPException(400, "La solicitud está incompleta. Pedile que se registre de nuevo.")

    user = UserAccount(
        email=req.email,
        password_hash=pwhash,
        display_name=req.display_name,
        locale=locale,
        timezone=settings.default_timezone,
        status=UserStatus.ACTIVE,
        is_instance_admin=False,
    )
    db.add(user)
    await db.flush()

    db.add(TermsAcceptance(user_id=user.id, legal_document_id=terms_id))

    req.reviewed_at = datetime.now(UTC)
    req.reviewed_by = admin.id
    req.approved = True
    # The password hash is dropped once the account exists.
    req.note = note.split("\n[pwhash:")[0]

    await record(
        db, action=AuditAction.USER_APPROVED, actor_id=admin.id,
        entity_type="user_account", entity_id=user.id,
        detail={"email": req.email}, ip_hash=client_ip_hash(request),
    )
    return {"status": "approved", "user_id": str(user.id)}


@router.post("/admin/registrations/{request_id}/reject")
async def reject_registration(
    request: Request,
    request_id: uuid.UUID,
    admin: InstanceAdmin,
    db: Db,
    reason: Annotated[str, Form()] = "",
    _csrf: CsrfChecked = None,
) -> dict:
    req = await db.get(RegistrationRequest, request_id)
    if req is None or req.reviewed_at is not None:
        raise HTTPException(404, "Solicitud no encontrada o ya revisada.")

    req.reviewed_at = datetime.now(UTC)
    req.reviewed_by = admin.id
    req.approved = False
    req.rejection_reason = reason.strip() or None
    req.note = (req.note or "").split("\n[pwhash:")[0]

    await record(
        db, action=AuditAction.USER_REJECTED, actor_id=admin.id,
        detail={"email": req.email}, ip_hash=client_ip_hash(request),
    )
    return {"status": "rejected"}


# -----------------------------------------------------------------------------
# Login / logout
# -----------------------------------------------------------------------------


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    db: Db,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> dict:
    email = email.strip().lower()
    ip = client_ip_hash(request)

    # Throttle by account and by source. Per-account alone lets one attacker
    # lock a victim out; per-IP alone is defeated by a botnet.
    for key in (f"email:{email}", f"ip:{ip}"):
        if await is_login_locked(key):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Demasiados intentos. Probá de nuevo en {settings.login_lockout_minutes} minutos.",
            )

    user = (
        await db.execute(select(UserAccount).where(UserAccount.email == email))
    ).scalar_one_or_none()

    ok, new_hash = verify_password(password, user.password_hash if user else None)

    if not ok or user is None or not user.can_log_in:
        await register_failed_login(f"email:{email}")
        await register_failed_login(f"ip:{ip}")
        await record(
            db, action=AuditAction.LOGIN_FAILED,
            actor_id=user.id if user else None,
            detail={"email": email}, ip_hash=ip,
        )
        # One message for every failure mode: wrong password, no such account,
        # suspended, still pending approval.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales inválidas.")

    if new_hash:
        user.password_hash = new_hash  # transparent upgrade to current params

    await clear_failed_logins(f"email:{email}")
    await clear_failed_logins(f"ip:{ip}")

    user.last_login_at = datetime.now(UTC)
    raw_sid, session = await create_session(
        user.id, ip_hash=ip, user_agent=request.headers.get("user-agent")
    )
    _set_session_cookie(response, raw_sid)

    await record(db, action=AuditAction.LOGIN_SUCCESS, actor_id=user.id, ip_hash=ip)
    return {
        "status": "ok",
        "user": {"id": str(user.id), "display_name": user.display_name,
                 "locale": user.locale, "is_instance_admin": user.is_instance_admin},
        "csrf_token": session.csrf_token,
    }


@router.post("/logout")
async def logout(request: Request, response: Response, db: Db, user: CurrentUser) -> dict:
    raw_sid = request.cookies.get(settings.session_cookie_name)
    if raw_sid:
        await destroy_session(raw_sid)
    response.delete_cookie(settings.session_cookie_name, path="/")
    await record(db, action=AuditAction.LOGOUT, actor_id=user.id,
                 ip_hash=client_ip_hash(request))
    return {"status": "ok"}


@router.post("/logout-everywhere")
async def logout_everywhere(
    request: Request, response: Response, db: Db, user: CurrentUser,
    _csrf: CsrfChecked = None,
) -> dict:
    killed = await destroy_all_sessions(user.id)
    response.delete_cookie(settings.session_cookie_name, path="/")
    await record(db, action=AuditAction.SESSIONS_REVOKED, actor_id=user.id,
                 detail={"sessions": killed}, ip_hash=client_ip_hash(request))
    return {"status": "ok", "sessions_closed": killed}


@router.post("/account/password")
async def change_password(
    request: Request,
    response: Response,
    db: Db,
    user: CurrentUser,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    _csrf: CsrfChecked = None,
) -> dict:
    ok, _ = verify_password(current_password, user.password_hash)
    if not ok:
        raise HTTPException(400, "La contraseña actual no es correcta.")

    problems = password_problems(new_password)
    if problems:
        raise HTTPException(400, " ".join(problems))

    user.password_hash = hash_password(new_password)
    # Every other session dies. A password change is usually a reaction to
    # something, so leaving old sessions alive defeats the point.
    await destroy_all_sessions(user.id)
    raw_sid, session = await create_session(
        user.id, ip_hash=client_ip_hash(request),
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookie(response, raw_sid)

    await record(db, action=AuditAction.PASSWORD_CHANGED, actor_id=user.id,
                 ip_hash=client_ip_hash(request))
    return {"status": "ok", "csrf_token": session.csrf_token}


@router.post("/admin/users/{user_id}/suspend")
async def suspend_user(
    request: Request, user_id: uuid.UUID, admin: InstanceAdmin, db: Db,
    _csrf: CsrfChecked = None,
) -> dict:
    target = await db.get(UserAccount, user_id)
    if target is None:
        raise HTTPException(404, "Usuario no encontrado.")
    if target.id == admin.id:
        raise HTTPException(400, "No podés suspenderte a vos mismo.")

    target.status = UserStatus.SUSPENDED
    killed = await destroy_all_sessions(target.id)  # takes effect immediately

    await record(db, action=AuditAction.USER_SUSPENDED, actor_id=admin.id,
                 entity_type="user_account", entity_id=target.id,
                 detail={"sessions_closed": killed}, ip_hash=client_ip_hash(request))
    return {"status": "suspended", "sessions_closed": killed}
