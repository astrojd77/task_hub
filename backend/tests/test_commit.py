"""Commit is the only door into the store — so it gets the most tests."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from app.models.task import Task
from app.schemas.task import TaskCommitIn
from app.services.commit import commit_drafts


def draft(**overrides) -> TaskCommitIn:
    base = {
        "summary": "Rotate the signing certificate",
        "source_provider": "csv",
        "source_ref": "row-1",
    }
    return TaskCommitIn(**(base | overrides))


def count(db) -> int:
    return db.execute(select(func.count()).select_from(Task)).scalar_one()


def test_commit_persists_a_task(db):
    result = commit_drafts(db, [draft(due_date=date(2026, 8, 1))])

    assert result.created == 1
    assert result.updated == 0
    assert count(db) == 1

    task = db.execute(select(Task)).scalar_one()
    assert task.summary == "Rotate the signing certificate"
    assert task.status == "todo"
    assert task.priority == "medium"
    assert task.destination == "local"
    assert task.id  # uuid generated in Python, not by the database


def test_reimport_updates_and_does_not_duplicate(db):
    commit_drafts(db, [draft(summary="Original")])
    result = commit_drafts(db, [draft(summary="Renamed upstream")])

    assert result.created == 0
    assert result.updated == 1
    assert count(db) == 1
    assert db.execute(select(Task)).scalar_one().summary == "Renamed upstream"


def test_same_source_ref_twice_in_one_batch_collapses(db):
    """A CSV with a repeated row must not blow up on the unique constraint."""
    result = commit_drafts(db, [draft(summary="First"), draft(summary="Second")])

    assert (result.created, result.updated) == (1, 1)
    assert count(db) == 1
    assert db.execute(select(Task)).scalar_one().summary == "Second"


def test_same_ref_from_different_sources_are_distinct_tasks(db):
    commit_drafts(db, [draft(source_provider="csv", source_ref="ABC-1")])
    commit_drafts(db, [draft(source_provider="jira", source_ref="ABC-1")])

    assert count(db) == 2


def test_missing_due_date_warns_but_still_commits(db):
    result = commit_drafts(db, [draft(due_date=None)])

    assert result.created == 1
    assert any("due date" in w.message for w in result.warnings)


def test_missing_criticality_warns(db):
    result = commit_drafts(db, [draft(due_date=date(2026, 8, 1))])

    assert any("criticality" in w.message for w in result.warnings)


def test_unknown_destination_is_a_row_error_not_a_batch_failure(db):
    result = commit_drafts(
        db,
        [
            draft(source_ref="good", destination="local"),
            draft(source_ref="bad", destination="myspace"),
        ],
    )

    assert result.created == 1
    assert len(result.errors) == 1
    assert result.errors[0].source_ref == "bad"
    assert count(db) == 1


def test_enums_are_stored_as_plain_strings(db):
    """StrEnum must not reach the column as an enum instance."""
    commit_drafts(
        db,
        [draft(status="blocked", priority="urgent", criticality="critical", impact_size="xl")],
    )

    row = db.execute(select(Task)).scalar_one()
    assert (row.status, row.priority, row.criticality, row.impact_size) == (
        "blocked",
        "urgent",
        "critical",
        "xl",
    )
    assert all(isinstance(v, str) and not hasattr(v, "value") for v in (row.status, row.priority))


def test_json_columns_round_trip(db):
    commit_drafts(db, [draft(labels=["security", "q3"], raw_payload={"nested": {"n": 1}})])

    row = db.execute(select(Task)).scalar_one()
    assert row.labels == ["security", "q3"]
    assert row.raw_payload == {"nested": {"n": 1}}
    assert row.external_refs == {}


@pytest.mark.parametrize("bad_title", ["", "   "])
def test_blank_summary_is_rejected(bad_title):
    with pytest.raises(ValueError):
        draft(summary=bad_title)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "almost_done"),
        ("priority", "p0"),
        ("criticality", "showstopper"),
        ("impact_size", "huge"),
    ],
)
def test_off_scale_enum_values_are_rejected(field, value):
    with pytest.raises(ValueError):
        draft(**{field: value})
