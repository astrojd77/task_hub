"""The canonical Task.

One table, one vocabulary. Sources map *into* a draft of this shape;
destinations map *out of* a committed row. Nothing platform-specific belongs
here — platform data lives in ``raw_payload`` (provenance) and
``external_refs`` (where this task has been pushed).

Enum-valued columns are plain ``VARCHAR`` rather than DB enums or CHECK
constraints: the canonical scales are meant to be tunable, and validation is
server-authoritative in the Pydantic layer (see ``app.schemas.task``), which is
what "the UI must not be the only gate" requires. Adding a scale value must not
require a migration.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Date, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import Priority, TaskStatus
from app.db.base import Base
from app.db.types import PortableJSON, UTCDateTime


def new_uuid() -> str:
    """UUIDs are generated in Python and stored as VARCHAR2(36).

    Oracle has no ``gen_random_uuid()`` and SQLAlchemy's native UUID type is not
    portable across all three target dialects.
    """
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Naive UTC. All timestamps in this schema are UTC by convention.

    SQLite cannot round-trip tz-aware values, so storing naive-UTC everywhere is
    the portable choice; the API layer stamps them as UTC on the way out.
    """
    return datetime.now(UTC).replace(tzinfo=None)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        # Idempotency: re-importing the same item from the same source updates
        # the existing row rather than creating a second one.
        UniqueConstraint("source_provider", "source_ref", name="uq_tasks_source"),
        Index("ix_tasks_due_date", "due_date"),
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_project", "project"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TaskStatus.TODO.value)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default=Priority.MEDIUM.value)
    criticality: Mapped[str | None] = mapped_column(String(20), nullable=True)
    impact_size: Mapped[str | None] = mapped_column(String(20), nullable=True)

    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(200), nullable=True)
    project: Mapped[str | None] = mapped_column(String(200), nullable=True)

    labels: Mapped[list[str]] = mapped_column(PortableJSON, nullable=False, default=list)

    # Kept short so the composite unique index stays well inside Oracle's
    # index-key byte limit under AL32UTF8.
    source_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False)

    #: {destination_provider: external_id}, populated on push.
    external_refs: Mapped[dict] = mapped_column(PortableJSON, nullable=False, default=dict)
    #: Original source data, for provenance and debugging.
    raw_payload: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)

    #: Chosen destination for this task; falls back to the project default.
    destination: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Task {self.id} {self.source_provider}:{self.source_ref} {self.title!r}>"
