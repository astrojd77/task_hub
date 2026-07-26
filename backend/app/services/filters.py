"""Shared task filtering.

The list, calendar and watch views all expose the same facets. They share this
one filter object so the three views can never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from fastapi import Query
from sqlalchemy import Select, or_

from app.models.task import Task


@dataclass
class TaskFilters:
    source: list[str] = field(default_factory=list)
    destination: list[str] = field(default_factory=list)
    project: list[str] = field(default_factory=list)
    status: list[str] = field(default_factory=list)
    assignee: list[str] = field(default_factory=list)
    criticality: list[str] = field(default_factory=list)
    impact_size: list[str] = field(default_factory=list)
    priority: list[str] = field(default_factory=list)
    due_from: date | None = None
    due_to: date | None = None
    q: str | None = None

    def apply(self, stmt: Select) -> Select:
        if self.source:
            stmt = stmt.where(Task.source_provider.in_(self.source))
        if self.destination:
            stmt = stmt.where(Task.destination.in_(self.destination))
        if self.project:
            stmt = stmt.where(Task.project.in_(self.project))
        if self.status:
            stmt = stmt.where(Task.status.in_(self.status))
        if self.assignee:
            stmt = stmt.where(Task.assignee.in_(self.assignee))
        if self.criticality:
            stmt = stmt.where(Task.criticality.in_(self.criticality))
        if self.impact_size:
            stmt = stmt.where(Task.impact_size.in_(self.impact_size))
        if self.priority:
            stmt = stmt.where(Task.priority.in_(self.priority))
        if self.due_from is not None:
            stmt = stmt.where(Task.due_date >= self.due_from)
        if self.due_to is not None:
            stmt = stmt.where(Task.due_date <= self.due_to)
        if self.q:
            like = f"%{self.q}%"
            # SQLAlchemy's ilike() emits native ILIKE on Postgres and
            # lower(a) LIKE lower(b) everywhere else, so this is portable.
            stmt = stmt.where(
                or_(
                    Task.title.ilike(like),
                    Task.description.ilike(like),
                )
            )
        return stmt


def task_filters(
    source: list[str] = Query(default=[]),
    destination: list[str] = Query(default=[]),
    project: list[str] = Query(default=[]),
    status: list[str] = Query(default=[]),
    assignee: list[str] = Query(default=[]),
    criticality: list[str] = Query(default=[]),
    impact_size: list[str] = Query(default=[]),
    priority: list[str] = Query(default=[]),
    due_from: date | None = Query(default=None),
    due_to: date | None = Query(default=None),
    q: str | None = Query(default=None),
) -> TaskFilters:
    return TaskFilters(
        source=source,
        destination=destination,
        project=project,
        status=status,
        assignee=assignee,
        criticality=criticality,
        impact_size=impact_size,
        priority=priority,
        due_from=due_from,
        due_to=due_to,
        q=q,
    )
