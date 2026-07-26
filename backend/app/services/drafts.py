"""Turning a source's output into a review-ready batch.

This is the step between ``fetch`` and the review UI. It never writes.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import islice
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.task import Task
from app.providers.base import ProviderError, SourceProvider
from app.schemas.task import DraftBatch, DraftTask

#: Fields a user typically fills in during review and that sources rarely
#: supply. If a re-import leaves one blank, we put the previously reviewed
#: value back rather than silently dropping the user's work.
_REVIEW_FIELDS = ("criticality", "impact_size", "due_date", "assignee", "project")

#: Oracle rejects an IN list longer than 1000 entries (ORA-01795), and a CSV
#: import can carry thousands of rows, so the lookup is always chunked.
_IN_CHUNK = 500


def build_batch(
    db: Session,
    provider: SourceProvider,
    config: dict[str, Any],
) -> DraftBatch:
    items = provider.fetch(config)
    drafts = [provider.to_draft(item) for item in items]

    if len(drafts) != len(items):  # pragma: no cover - defensive
        raise ProviderError(f"{provider.id} returned a draft count that does not match its items")

    enrich_with_existing(db, drafts)

    describe = getattr(provider, "describe", None)
    meta = describe(config) if callable(describe) else {}

    warnings: list[str] = []
    if not drafts:
        warnings.append("nothing to import — the source returned no items")

    return DraftBatch(
        source_provider=provider.id,
        drafts=drafts,
        warnings=warnings,
        meta=meta or {},
    )


def enrich_with_existing(db: Session, drafts: list[DraftTask]) -> None:
    """Mark drafts that were imported before and restore reviewed values.

    A source is authoritative for what it knows: anything it supplied is left
    alone. Only fields it left empty are back-filled from the committed task,
    and the draft is flagged so the review screen can say why. The decision
    then sits in front of the user rather than inside a merge rule.
    """
    if not drafts:
        return

    refs_by_provider: dict[str, set[str]] = defaultdict(set)
    for draft in drafts:
        refs_by_provider[draft.source_provider].add(draft.source_ref)

    existing: dict[tuple[str, str], Task] = {}
    for provider_id, refs in refs_by_provider.items():
        remaining = iter(sorted(refs))
        while chunk := list(islice(remaining, _IN_CHUNK)):
            rows = db.execute(
                select(Task).where(
                    Task.source_provider == provider_id,
                    Task.source_ref.in_(chunk),
                )
            ).scalars()
            existing.update({(t.source_provider, t.source_ref): t for t in rows})

    if not existing:
        return

    for draft in drafts:
        task = existing.get((draft.source_provider, draft.source_ref))
        if task is None:
            continue

        draft.existing_task_id = task.id
        restored = [
            field
            for field in _REVIEW_FIELDS
            if getattr(draft, field) is None and getattr(task, field) is not None
        ]
        for field in restored:
            setattr(draft, field, getattr(task, field))

        if restored:
            draft.warnings.append(
                "already imported — kept your reviewed " + ", ".join(restored)
            )
        else:
            draft.warnings.append("already imported — committing will update the existing task")
