"""Authorization: capabilities, the role matrix, and the consent gate.

The single rule of this module: **routes never check roles**. They declare the
capability they need and this file decides. Scattering `if role == "editor"`
across handlers is how authorization bugs are born, because the twentieth
handler is the one that forgets.

Three independent gates apply, in this order:

  1. Account gate    - is the user active at all
  2. Role gate       - does their role on this logbook grant the capability
  3. Consent gate    - has the subject's consent been revoked

A capability must clear all three. Consent is separate from role on purpose:
with consent revoked even an owner loses write access, while read and export
survive, because the subject's own right of access depends on being able to
get their data back out.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from app.models.enums import LogbookStatus, MembershipRole


class Permission(str, enum.Enum):
    """What a user may do inside one logbook.

    Named after the action, not the role. Adding a feature means adding a
    capability here and one row in the matrix below, which is a change you
    are forced to think about.
    """

    # --- reading ---------------------------------------------------------
    VIEW_LOGBOOK = "logbook.view"
    VIEW_DOCUMENT = "document.view"
    DOWNLOAD_DOCUMENT = "document.download"
    VIEW_OBSERVATION = "observation.view"
    VIEW_JOURNAL = "journal.view"
    VIEW_EPISODE = "episode.view"
    VIEW_AUDIT_LOG = "audit.view"
    EXPORT_LOGBOOK = "logbook.export"

    # --- commenting ------------------------------------------------------
    CREATE_COMMENT = "comment.create"
    DELETE_OWN_COMMENT = "comment.delete_own"
    DELETE_ANY_COMMENT = "comment.delete_any"

    # --- writing ---------------------------------------------------------
    UPLOAD_DOCUMENT = "document.upload"
    EDIT_DOCUMENT = "document.edit"
    DELETE_DOCUMENT = "document.delete"
    CONFIRM_OBSERVATION = "observation.confirm"
    EDIT_OBSERVATION = "observation.edit"
    RECORD_HOME_READING = "observation.record_home"
    WRITE_JOURNAL = "journal.write"
    MANAGE_TRACKING_PLAN = "tracking_plan.manage"
    MANAGE_EPISODE = "episode.manage"
    POST_EPISODE_UPDATE = "episode.post_update"
    MANAGE_TAGS = "tag.manage"

    # --- sharing ---------------------------------------------------------
    CREATE_SHARE = "share.create"
    REVOKE_SHARE = "share.revoke"
    VIEW_SHARE_ACCESS_LOG = "share.view_access_log"

    # --- administration of the logbook ------------------------------------
    INVITE_MEMBER = "member.invite"
    CHANGE_MEMBER_ROLE = "member.change_role"
    REMOVE_MEMBER = "member.remove"
    TRANSFER_OWNERSHIP = "logbook.transfer_ownership"
    EDIT_LOGBOOK_SETTINGS = "logbook.edit_settings"
    MANAGE_CONSENT = "consent.manage"
    DELETE_LOGBOOK = "logbook.delete"


# -----------------------------------------------------------------------------
# The matrix. Defined additively: each role gets the one below it, plus more.
# -----------------------------------------------------------------------------

_VIEWER: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_LOGBOOK,
        Permission.VIEW_DOCUMENT,
        Permission.DOWNLOAD_DOCUMENT,
        Permission.VIEW_OBSERVATION,
        Permission.VIEW_JOURNAL,
        Permission.VIEW_EPISODE,
    }
)

_COMMENTER: frozenset[Permission] = _VIEWER | {
    Permission.CREATE_COMMENT,
    Permission.DELETE_OWN_COMMENT,
}

_EDITOR: frozenset[Permission] = _COMMENTER | {
    Permission.UPLOAD_DOCUMENT,
    Permission.EDIT_DOCUMENT,
    Permission.DELETE_DOCUMENT,
    # Confirming an extracted value is an editor act: it promotes machine
    # output to trusted data, which is the whole point of the review queue.
    Permission.CONFIRM_OBSERVATION,
    Permission.EDIT_OBSERVATION,
    Permission.RECORD_HOME_READING,
    Permission.WRITE_JOURNAL,
    Permission.MANAGE_TRACKING_PLAN,
    Permission.MANAGE_EPISODE,
    Permission.POST_EPISODE_UPDATE,
    Permission.MANAGE_TAGS,
    Permission.CREATE_SHARE,
    Permission.REVOKE_SHARE,
    Permission.VIEW_SHARE_ACCESS_LOG,
    Permission.EXPORT_LOGBOOK,
}

_OWNER: frozenset[Permission] = _EDITOR | {
    Permission.INVITE_MEMBER,
    Permission.CHANGE_MEMBER_ROLE,
    Permission.REMOVE_MEMBER,
    Permission.TRANSFER_OWNERSHIP,
    Permission.EDIT_LOGBOOK_SETTINGS,
    Permission.MANAGE_CONSENT,
    Permission.DELETE_LOGBOOK,
    Permission.DELETE_ANY_COMMENT,
    Permission.VIEW_AUDIT_LOG,
}

ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.VIEWER: _VIEWER,
    MembershipRole.COMMENTER: _COMMENTER,
    MembershipRole.EDITOR: _EDITOR,
    MembershipRole.OWNER: _OWNER,
}


# -----------------------------------------------------------------------------
# Consent gate
# -----------------------------------------------------------------------------

# Survives consent revocation. Read and export stay available so the subject
# can still exercise their right of access, and so the owner can get the data
# out in order to delete the logbook. Everything else stops, including every
# form of sharing.
_ALLOWED_WITHOUT_CONSENT: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_LOGBOOK,
        Permission.VIEW_DOCUMENT,
        Permission.DOWNLOAD_DOCUMENT,
        Permission.VIEW_OBSERVATION,
        Permission.VIEW_JOURNAL,
        Permission.VIEW_EPISODE,
        Permission.VIEW_AUDIT_LOG,
        Permission.EXPORT_LOGBOOK,
        Permission.MANAGE_CONSENT,   # so consent can be granted again
        Permission.DELETE_LOGBOOK,
        Permission.REVOKE_SHARE,     # revoking is always allowed
    }
)

# An archived logbook is read-only, full stop.
_ALLOWED_WHEN_ARCHIVED: frozenset[Permission] = _ALLOWED_WITHOUT_CONSENT


@dataclass(frozen=True, slots=True)
class AccessContext:
    """Everything needed to answer "may this user do this here", resolved once
    per request and reused. Frozen so a handler cannot quietly widen its own
    permissions mid-request.
    """

    user_id: object
    logbook_id: object
    role: MembershipRole
    logbook_status: LogbookStatus

    def granted(self) -> frozenset[Permission]:
        """Effective permissions after every gate."""
        by_role = ROLE_PERMISSIONS[self.role]
        if self.logbook_status is LogbookStatus.CONSENT_REVOKED:
            return by_role & _ALLOWED_WITHOUT_CONSENT
        if self.logbook_status is LogbookStatus.ARCHIVED:
            return by_role & _ALLOWED_WHEN_ARCHIVED
        return by_role

    def can(self, permission: Permission) -> bool:
        return permission in self.granted()

    def why_denied(self, permission: Permission) -> str:
        """A message the UI can show without leaking what else exists."""
        if permission in ROLE_PERMISSIONS[self.role]:
            if self.logbook_status is LogbookStatus.CONSENT_REVOKED:
                return (
                    "El consentimiento del titular fue revocado. "
                    "La bitácora quedó en modo solo lectura."
                )
            if self.logbook_status is LogbookStatus.ARCHIVED:
                return "La bitácora está archivada y es de solo lectura."
        return "Tu rol en esta bitácora no permite esta acción."


def role_can(role: MembershipRole, permission: Permission) -> bool:
    """Role check ignoring logbook state. Use only for UI hints, never to
    authorize an action: the consent gate is not optional."""
    return permission in ROLE_PERMISSIONS[role]


def assignable_roles() -> list[MembershipRole]:
    """Roles an owner may hand out. Ownership is transferred, never granted,
    so that a logbook always has exactly one owner."""
    return [
        MembershipRole.VIEWER,
        MembershipRole.COMMENTER,
        MembershipRole.EDITOR,
    ]
