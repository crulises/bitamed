"""Logbook, membership, invitations and subject consent."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, pg_enum, updated_at, uuid_pk
from app.models.enums import ConsentCapacity, LogbookStatus, MembershipRole


class Logbook(Base):
    """One person's record. The unit of permission, consent and sharing."""

    __tablename__ = "logbook"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)

    patient_given_name: Mapped[str] = mapped_column(Text)
    patient_family_name: Mapped[str] = mapped_column(Text)
    patient_birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    patient_sex: Mapped[str | None] = mapped_column(Text, nullable=True)
    patient_national_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    blood_type: Mapped[str | None] = mapped_column(Text, nullable=True)

    default_locale: Mapped[str] = mapped_column(Text, default="es")
    ocr_languages: Mapped[str] = mapped_column(Text, default="spa+por")
    status: Mapped[LogbookStatus] = mapped_column(
        pg_enum(LogbookStatus, "logbook_status")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_account.id")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    @property
    def is_writable(self) -> bool:
        """Consent gates writes, not the role matrix.

        With consent revoked the record becomes read-only for its members:
        they can still read and export (the subject's own right of access
        depends on it), but nothing new gets recorded and no link works.
        """
        return self.status == LogbookStatus.ACTIVE


class Membership(Base):
    __tablename__ = "membership"

    logbook_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("logbook.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("user_account.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[MembershipRole] = mapped_column(
        pg_enum(MembershipRole, "membership_role")
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_account.id"), nullable=True
    )
    invited_at: Mapped[datetime] = created_at()
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Invitation(Base):
    """A pending invitation to join a logbook.

    The token lives only in the emailed URL; we store its hash. Owners are
    never invited: ownership is transferred between existing members.
    """

    __tablename__ = "invitation"

    id: Mapped[uuid.UUID] = uuid_pk()
    logbook_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("logbook.id", ondelete="CASCADE")
    )
    email: Mapped[str] = mapped_column(Text)
    role: Mapped[MembershipRole] = mapped_column(
        pg_enum(MembershipRole, "membership_role")
    )
    token_hash: Mapped[str] = mapped_column(Text)
    invited_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_account.id")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = created_at()

    def is_usable(self, now: datetime) -> bool:
        return (
            self.accepted_at is None
            and self.revoked_at is None
            and self.expires_at > now
        )


class SubjectConsent(Base):
    """The data subject's authorization, per logbook.

    This is the lawful basis for holding a third party's health data. It is
    revocable, and revoking it fires a database trigger that kills every
    active share on the logbook.
    """

    __tablename__ = "subject_consent"

    id: Mapped[uuid.UUID] = uuid_pk()
    logbook_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("logbook.id", ondelete="CASCADE")
    )
    legal_document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("legal_document.id")
    )
    subject_name: Mapped[str] = mapped_column(Text)
    capacity: Mapped[ConsentCapacity] = mapped_column(
        pg_enum(ConsentCapacity, "consent_capacity")
    )
    representative_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    granted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_account.id")
    )
    granted_at: Mapped[datetime] = created_at()
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revocation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )


Boolean  # re-exported for model modules that extend this one

__all__ = ["Invitation", "Logbook", "Membership", "SubjectConsent"]
