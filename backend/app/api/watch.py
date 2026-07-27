"""GET /api/watch — computed heads-up over committed tasks."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.task import TaskOut
from app.services.filters import TaskFilters, task_filters
from app.services.watch import DEFAULT_WEIGHTS, build_watch

router = APIRouter(prefix="/watch", tags=["watch"])


class WatchItem(BaseModel):
    task: TaskOut
    score: int
    #: Why this score — shown in the UI so the ranking is never a black box.
    reasons: list[str]
    sections: list[str]


class WatchSection(BaseModel):
    key: str
    label: str
    description: str
    items: list[WatchItem]


class WatchOut(BaseModel):
    today: date
    weights: dict
    sections: list[WatchSection]


_SECTION_LABELS = {
    "overdue": ("Overdue", "Past its due date and not done."),
    "due_soon": ("Due soon", "Lands inside the watch window."),
    "keep_an_eye_on": (
        "Keep an eye on",
        "High criticality or large blast radius, whatever the date.",
    ),
    "blocked": ("Blocked", "Waiting on something."),
}


@router.get("", response_model=WatchOut)
def watch(
    filters: TaskFilters = Depends(task_filters),
    today: date | None = Query(
        default=None,
        description="Override the reference date. Exists so the view is testable and so "
        "you can look ahead; defaults to the server's UTC date.",
    ),
    db: Session = Depends(get_db),
) -> WatchOut:
    reference = today or datetime.now(UTC).date()
    result = build_watch(db, filters, reference, DEFAULT_WEIGHTS)

    sections = []
    for key, items in result["buckets"].items():
        label, description = _SECTION_LABELS[key]
        sections.append(
            WatchSection(
                key=key,
                label=label,
                description=description,
                items=[
                    WatchItem(
                        task=TaskOut.model_validate(i.task),
                        score=i.score,
                        reasons=i.reasons,
                        sections=i.sections,
                    )
                    for i in items
                ],
            )
        )

    return WatchOut(today=reference, weights=DEFAULT_WEIGHTS.as_dict(), sections=sections)
