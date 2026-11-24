"""Python mirrors of the Postgres enum types in db/001-sch.sql.

Only the enums phase 2 (auth, roles, permissions) code touches are defined
here. The rest of the schema's enums (study_type, observation_status,
share_scope, ...) belong to phases 1 and 3, whose ORM models don't exist
yet — see the "ORM models cover only part of the schema" note in CLAUDE.md.

Member values must match the Postgres enum labels exactly; app.models.base
.pg_enum() stores .value, not .name.
"""

import enum


class UserStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class MembershipRole(str, enum.Enum):
    OWNER = "owner"
    EDITOR = "editor"
    COMMENTER = "commenter"
    VIEWER = "viewer"


class LegalKind(str, enum.Enum):
    TERMS = "terms"
    PRIVACY = "privacy"
    SUBJECT_CONSENT = "subject_consent"


class ConsentCapacity(str, enum.Enum):
    SELF = "self"
    LEGAL_REPRESENTATIVE = "legal_representative"


class LogbookStatus(str, enum.Enum):
    ACTIVE = "active"
    CONSENT_REVOKED = "consent_revoked"
    ARCHIVED = "archived"
