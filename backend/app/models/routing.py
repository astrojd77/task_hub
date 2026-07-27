"""Per-project default destination.

Routing resolves in three steps, most specific first:

    task.destination  ->  project default  ->  "local"

A per-task choice always wins; the project default is the convenience layer so
you are not setting a destination on every task in a workstream.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime
from app.models.task import new_uuid, utcnow


class ProjectRoute(Base):
    __tablename__ = "project_routes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    #: Matches Task.project. Unique so a project has exactly one default.
    project: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    destination: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<ProjectRoute {self.project!r} -> {self.destination!r}>"
