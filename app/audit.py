"""Audit logging.

Every privileged action writes a row. Cheap to add now, impossible to
reconstruct later, and the first thing anyone asks for when something looks
wrong: who changed this, and when.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import AuditLog


class AuditAction:
    """Action names. Constants rather than free strings, so a typo does not
    quietly create a category nobody ever greps for."""

    USER_REGISTERED = "user.registered"
    USER_APPROVED = "user.approved"
    USER_REJECTED = "user.rejected"
    USER_SUSPENDED = "user.suspended"
    USER_REACTIVATED = "user.reactivated"
    LOGIN_SUCCESS = "auth.login"
    LOGIN_FAILED = "auth.login_failed"
    LOGOUT = "auth.logout"
    PASSWORD_CHANGED = "auth.password_changed"
    SESSIONS_REVOKED = "auth.sessions_revoked"

    LOGBOOK_CREATED = "logbook.created"
    LOGBOOK_SETTINGS_CHANGED = "logbook.settings_changed"
    LOGBOOK_DELETED = "logbook.deleted"
    OWNERSHIP_TRANSFERRED = "logbook.ownership_transferred"

    MEMBER_INVITED = "member.invited"
    INVITATION_ACCEPTED = "member.invitation_accepted"
    INVITATION_REVOKED = "member.invitation_revoked"
    MEMBER_ROLE_CHANGED = "member.role_changed"
    MEMBER_REMOVED = "member.removed"

    CONSENT_GRANTED = "consent.granted"
    CONSENT_REVOKED = "consent.revoked"

    PERMISSION_DENIED = "auth.permission_denied"


async def record(
    db: AsyncSession,
    *,
    action: str,
    actor_id: uuid.UUID | None = None,
    logbook_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
    ip_hash: str | None = None,
) -> None:
    """Append an audit entry to the current transaction.

    Intentionally part of the caller's transaction: if the action rolls back,
    so does its audit row. An audit log full of things that never happened is
    worse than no audit log.
    """
    db.add(
        AuditLog(
            action=action,
            actor_id=actor_id,
            logbook_id=logbook_id,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail or {},
            ip_hash=ip_hash,
        )
    )
