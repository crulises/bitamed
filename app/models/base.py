"""Declarative base and column helpers shared by every ORM model.

`id` and timestamp defaults come from the database (gen_random_uuid(),
now()), not from Python, matching db/001-sch.sql — a row inserted by raw SQL
and one inserted through the ORM must be indistinguishable. `updated_at` is
kept current by the `touch_updated_at` trigger, not by the ORM, for the same
reason: schema.sql is the reference, the ORM covers only part of it.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=text("now()"))


def updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=text("now()"))


def pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    # create_type=False: the Postgres type already exists, created by
    # db/*.sql. The ORM must never issue its own CREATE TYPE.
    return Enum(
        enum_cls,
        name=name,
        create_type=False,
        values_callable=lambda obj: [member.value for member in obj],
    )
