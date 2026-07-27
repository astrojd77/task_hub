"""The Watch view: what's coming up and what to keep an eye on.

Read-only and computed at request time over committed tasks. No delivered
notifications in v1 — this is an in-app view, and a daily digest later would
reuse this module without changing it.

The score is deliberately a small, visible weight table rather than a learned
or hidden ranking. The point is being able to explain exactly why something is
near the top, and to reorder the whole view by turning one knob.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Criticality, ImpactSize, TaskStatus
from app.models.task import Task
from app.services.filters import TaskFilters


@dataclass(frozen=True)
class WatchWeights:
    """Every knob, in one place.

    Change a number here and the whole view reorders. Nothing else in the
    codebase gets an opinion about ranking.
    """

    criticality: dict[str, int] = field(
        default_factory=lambda: {
            Criticality.LOW: 0,
            Criticality.MEDIUM: 1,
            Criticality.HIGH: 3,
            Criticality.CRITICAL: 5,
        }
    )
    impact: dict[str, int] = field(
        default_factory=lambda: {
            ImpactSize.XS: 0,
            ImpactSize.S: 1,
            ImpactSize.M: 2,
            ImpactSize.L: 3,
            ImpactSize.XL: 4,
        }
    )
    overdue: int = 5
    due_within_2_days: int = 3
    due_within_7_days: int = 1
    blocked: int = 2

    #: "Due soon" window, in days. Also the boundary for the smallest due bonus.
    due_soon_days: int = 7

    def as_dict(self) -> dict:
        """Exposed by the API so the UI can show the working, not just the score."""
        return {
            "criticality": dict(self.criticality),
            "impact": dict(self.impact),
            "overdue": self.overdue,
            "due_within_2_days": self.due_within_2_days,
            "due_within_7_days": self.due_within_7_days,
            "blocked": self.blocked,
            "due_soon_days": self.due_soon_days,
        }


DEFAULT_WEIGHTS = WatchWeights()


@dataclass
class ScoredTask:
    task: Task
    score: int
    #: Human-readable breakdown — "criticality: critical +5", "overdue +5".
    reasons: list[str]
    sections: list[str]


def due_urgency(due: date | None, today: date, weights: WatchWeights) -> tuple[int, str | None]:
    if due is None:
        return 0, None
    delta = (due - today).days
    if delta < 0:
        return weights.overdue, f"overdue by {-delta}d +{weights.overdue}"
    if delta <= 2:
        return weights.due_within_2_days, f"due in {delta}d +{weights.due_within_2_days}"
    if delta <= weights.due_soon_days:
        return weights.due_within_7_days, f"due in {delta}d +{weights.due_within_7_days}"
    return 0, None


def score_task(task: Task, today: date, weights: WatchWeights = DEFAULT_WEIGHTS) -> ScoredTask:
    score = 0
    reasons: list[str] = []

    crit = weights.criticality.get(task.criticality or "", 0)
    if crit:
        reasons.append(f"criticality {task.criticality} +{crit}")
    score += crit

    impact = weights.impact.get(task.impact_size or "", 0)
    if impact:
        reasons.append(f"impact {task.impact_size} +{impact}")
    score += impact

    urgency, why = due_urgency(task.due_date, today, weights)
    score += urgency
    if why:
        reasons.append(why)

    if task.status == TaskStatus.BLOCKED:
        score += weights.blocked
        reasons.append(f"blocked +{weights.blocked}")

    return ScoredTask(
        task=task,
        score=score,
        reasons=reasons,
        sections=sections_for(task, today, weights),
    )


def sections_for(task: Task, today: date, weights: WatchWeights = DEFAULT_WEIGHTS) -> list[str]:
    """A task can legitimately appear in more than one section."""
    sections: list[str] = []

    if task.due_date is not None and task.due_date < today:
        sections.append("overdue")
    elif task.due_date is not None and (task.due_date - today).days <= weights.due_soon_days:
        sections.append("due_soon")

    if task.criticality in {Criticality.HIGH, Criticality.CRITICAL} or task.impact_size in {
        ImpactSize.L,
        ImpactSize.XL,
    }:
        sections.append("keep_an_eye_on")

    if task.status == TaskStatus.BLOCKED:
        sections.append("blocked")

    return sections


def build_watch(
    db: Session,
    filters: TaskFilters,
    today: date,
    weights: WatchWeights = DEFAULT_WEIGHTS,
) -> dict:
    """Score every open task, then bucket it into the sections it qualifies for."""
    # Done work is excluded from the view entirely — including from "overdue",
    # where a completed-but-late task is noise rather than a heads-up.
    stmt = filters.apply(select(Task)).where(Task.status != TaskStatus.DONE.value)
    tasks = list(db.execute(stmt).scalars())

    scored = [score_task(t, today, weights) for t in tasks]

    buckets: dict[str, list[ScoredTask]] = {
        "overdue": [],
        "due_soon": [],
        "keep_an_eye_on": [],
        "blocked": [],
    }
    for item in scored:
        for section in item.sections:
            buckets[section].append(item)

    for items in buckets.values():
        # Score first; due date breaks ties so equal-scoring work is ordered by
        # what lands soonest, and id last so the order is fully deterministic.
        items.sort(key=lambda s: (-s.score, s.task.due_date or date.max, s.task.id))

    return {"buckets": buckets, "scored": scored, "weights": weights}


def watch_window_end(today: date, weights: WatchWeights = DEFAULT_WEIGHTS) -> date:
    return today + timedelta(days=weights.due_soon_days)
