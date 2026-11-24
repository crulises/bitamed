"""Identity, legal acceptance and audit models."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, pg_enum, updated_at, uuid_pk
from app.models.enums import LegalKind, UserStatus


class UserAccount(Base):
    __tablename__ = "user_account"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text, default="es")
    timezone: Mapped[str] = mapped_column(Text)
    status: Mapped[UserStatus] = mapped_column(pg_enum(UserStatus, "user_status"))

    # Global flag. Deliberately narrow: an instance admin approves signups and
    # manages accounts. It grants NO access to the contents of any logbook.
    # Administering the server is not the same as being authorized to read
    # someone's medical record.
    is_instance_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    @property
    def can_log_in(self) -> bool:
        return self.status == UserStatus.ACTIVE


class RegistrationRequest(Base):
    __tablename__ = "registration_request"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = created_at()
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_account.id"), nullable=True
    )
    approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class LegalDocument(Base):
    """A versioned legal text. Published rows are immutable.

    Changing the terms means inserting a new version, never editing an
    existing row, so that "which text did this person accept" always has an
    exact answer years later.
    """

    __tablename__ = "legal_document"

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[LegalKind] = mapped_column(pg_enum(LegalKind, "legal_kind"))
    lang: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    body_md: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)


class TermsAcceptance(Base):
    """Accepted by a USER at signup. Governs the user/operator relationship.

    This is NOT the lawful basis for processing a third party's health data.
    That is SubjectConsent, which is per logbook.
    """

    __tablename__ = "terms_acceptance"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_account.id", ondelete="CASCADE")
    )
    legal_document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("legal_document.id")
    )
    accepted_at: Mapped[datetime] = created_at()
    ip_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base):
    """Append-only record of privileged actions. Never updated, never deleted."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = created_at()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_account.id"), nullable=True
    )
    logbook_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    ip_hash: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "AuditLog",
    "Date",
    "LegalDocument",
    "RegistrationRequest",
    "TermsAcceptance",
    "UserAccount",
]
