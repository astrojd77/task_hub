"""Commit: the single door into the task store.

No source writes to ``tasks`` directly. Everything arrives here, gets validated
a second time server-side, and is upserted idempotently on
``(source_provider, source_ref)``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.task import Task, utcnow
from app.providers.registry import registry
from app.schemas.task import (
    CommitError,
    CommitResult,
    CommitWarning,
    TaskCommitIn,
    TaskOut,
)
from app.services.field_config import validate_custom_fields

#: Fields copied verbatim from a reviewed draft onto the stored task.
_MUTABLE_FIELDS = (
    "title",
    "description",
    "status",
    "priority",
    "criticality",
    "impact_size",
    "due_date",
    "assignee",
    "project",
    "labels",
    "custom_fields",
)


def _resolve_destination(draft: TaskCommitIn, default_destination: str | None) -> str:
    chosen = draft.destination or default_destination or "local"
    # Raises KeyError for unknown/disabled providers; caller turns that into a
    # per-row error rather than failing the whole batch.
    registry.destination(chosen)
    return chosen


def _apply(task: Task, draft: TaskCommitIn) -> None:
    for name in _MUTABLE_FIELDS:
        value = getattr(draft, name)
        # Enums are StrEnum; store their plain string value so the column round
        # trips identically on every dialect.
        setattr(task, name, value.value if hasattr(value, "value") else value)


def commit_drafts(
    db: Session,
    drafts: list[TaskCommitIn],
    default_destination: str | None = None,
) -> CommitResult:
    result = CommitResult()

    for index, draft in enumerate(drafts):
        try:
            destination = _resolve_destination(draft, default_destination)
        except KeyError as exc:
            result.errors.append(
                CommitError(index=index, source_ref=draft.source_ref, message=str(exc))
            )
            continue

        if draft.due_date is None:
            result.warnings.append(
                CommitWarning(
                    index=index,
                    source_ref=draft.source_ref,
                    message="no due date — this task will not appear on the calendar",
                )
            )
        custom_errors = validate_custom_fields(db, draft.custom_fields)
        if custom_errors:
            for message in custom_errors:
                result.errors.append(
                    CommitError(index=index, source_ref=draft.source_ref, message=message)
                )
            continue

        if draft.criticality is None or draft.impact_size is None:
            result.warnings.append(
                CommitWarning(
                    index=index,
                    source_ref=draft.source_ref,
                    message="criticality/impact not set — watch score will under-rank this task",
                )
            )

        existing = db.execute(
            select(Task).where(
                Task.source_provider == draft.source_provider,
                Task.source_ref == draft.source_ref,
            )
        ).scalar_one_or_none()

        if existing is None:
            task = Task(
                source_provider=draft.source_provider,
                source_ref=draft.source_ref,
                destination=destination,
                raw_payload=draft.raw_payload,
                external_refs={},
            )
            _apply(task, draft)
            db.add(task)
            result.created += 1
        else:
            task = existing
            _apply(task, draft)
            task.destination = destination
            if draft.raw_payload is not None:
                task.raw_payload = draft.raw_payload
            task.updated_at = utcnow()
            result.updated += 1

        # Flush per row so a duplicate source_ref *within the same batch*
        # resolves to an update of the row we just added, not a constraint
        # violation at the end.
        db.flush()
        result.tasks.append(TaskOut.model_validate(task))

    db.commit()
    return result
