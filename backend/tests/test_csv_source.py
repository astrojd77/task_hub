"""CSV adapter: column mapping, value normalisation, idempotency keys."""

from __future__ import annotations

from datetime import date

import pytest

from app.providers.base import ProviderError, UploadedFile
from app.providers.sources.csv_source import CsvSource, read_csv, row_hash, suggest_mapping

SAMPLE = (
    "Summary,Details,State,Urgency,Severity,Impact,Due Date,Owner,Workstream,Tags\n"
    "Rotate signing cert,Expires soon,In Progress,P1,Sev 1,XL,2026-08-01,ana,Platform,security;q3\n"
    "Upgrade node pool,,Blocked,low,medium,s,2026-09-15,raj,Platform,infra\n"
)


def upload(text: str = SAMPLE, name: str = "tasks.csv") -> UploadedFile:
    return UploadedFile(filename=name, content=text.encode("utf-8"))


def drafts_for(text: str = SAMPLE, **config):
    src = CsvSource()
    cfg = {"file": upload(text), **config}
    return [src.to_draft(item) for item in src.fetch(cfg)]


# -- mapping ------------------------------------------------------------


def test_suggest_mapping_matches_common_header_spellings():
    columns = ["Summary", "Details", "State", "Urgency", "Severity", "Impact", "Due Date"]
    mapping = suggest_mapping(columns)

    assert mapping["title"] == "Summary"
    assert mapping["description"] == "Details"
    assert mapping["status"] == "State"
    assert mapping["priority"] == "Urgency"
    assert mapping["criticality"] == "Severity"
    assert mapping["impact_size"] == "Impact"
    assert mapping["due_date"] == "Due Date"


def test_a_column_is_never_mapped_to_two_fields():
    mapping = suggest_mapping(["Name", "Notes", "Due"])
    assert len(set(mapping.values())) == len(mapping)


def test_explicit_mapping_overrides_the_suggestion():
    text = "alpha,beta\nfirst,second\n"
    drafts = drafts_for(text, mapping={"title": "beta", "description": "alpha"})

    assert drafts[0].title == "second"
    assert drafts[0].description == "first"


def test_mapping_to_a_missing_column_is_ignored_not_fatal():
    drafts = drafts_for(mapping={"title": "Summary", "project": "NoSuchColumn"})
    assert drafts[0].project is None


# -- value normalisation -------------------------------------------------


def test_native_values_translate_to_canonical_enums():
    first, second = drafts_for()

    assert (first.status, first.priority) == ("in_progress", "high")  # P1 -> high
    assert (first.criticality, first.impact_size) == ("critical", "xl")
    assert (second.status, second.priority) == ("blocked", "low")
    assert (second.criticality, second.impact_size) == ("medium", "s")


def test_unmappable_enum_value_warns_and_stays_blank():
    text = "Summary,Severity\nDo a thing,catastrophic-ish\n"
    draft = drafts_for(text)[0]

    assert draft.criticality is None
    assert any("not on the scale" in w for w in draft.warnings)


def test_missing_title_is_flagged_for_review_not_dropped():
    text = "Summary,Owner\n,ana\n"
    draft = drafts_for(text)[0]

    assert draft.title == ""
    assert any("no title" in w for w in draft.warnings)


def test_dates_and_labels():
    first = drafts_for()[0]
    assert first.due_date == date(2026, 8, 1)
    assert first.labels == ["security", "q3"]


def test_ambiguous_slash_date_parses_but_warns():
    text = "Summary,Due Date\nThing,03/04/2026\n"
    draft = drafts_for(text)[0]

    assert draft.due_date == date(2026, 3, 4)
    assert any("month-first" in w for w in draft.warnings)


def test_unambiguous_slash_date_does_not_warn():
    text = "Summary,Due Date\nThing,12/25/2026\n"
    draft = drafts_for(text)[0]

    assert draft.due_date == date(2026, 12, 25)
    assert not any("month-first" in w for w in draft.warnings)


def test_unparseable_date_warns_and_leaves_it_blank():
    text = "Summary,Due Date\nThing,next tuesday\n"
    draft = drafts_for(text)[0]

    assert draft.due_date is None
    assert any("could not read" in w for w in draft.warnings)


def test_criticality_and_impact_default_to_blank_when_absent():
    """These are what the review popup exists to capture."""
    text = "Summary\nJust a title\n"
    draft = drafts_for(text)[0]

    assert draft.criticality is None
    assert draft.impact_size is None
    assert draft.status == "todo"
    assert draft.priority == "medium"


# -- idempotency keys ----------------------------------------------------


def test_row_hash_is_stable_and_content_addressed():
    row = {"a": "1", "b": "2"}
    assert row_hash(row) == row_hash({"b": "2", "a": "1"})
    assert row_hash(row) != row_hash({"a": "1", "b": "3"})


def test_same_file_yields_the_same_source_refs():
    assert [d.source_ref for d in drafts_for()] == [d.source_ref for d in drafts_for()]


def test_an_id_column_is_preferred_over_the_row_hash():
    text = "Key,Summary\nOPS-12,Thing\n"
    draft = drafts_for(text)[0]

    assert draft.source_ref == "OPS-12"


def test_row_hash_ignores_reviewed_edits_by_hashing_the_original_row():
    """Editing in review then re-importing must update, not duplicate."""
    original = drafts_for()[0]
    reimported = drafts_for()[0]

    original.title = "Renamed during review"
    assert original.source_ref == reimported.source_ref


# -- file handling -------------------------------------------------------


def test_semicolon_delimited_file():
    text = "Summary;Owner\nThing;ana\n"
    draft = drafts_for(text)[0]
    assert (draft.title, draft.assignee) == ("Thing", "ana")


def test_tab_delimited_file():
    text = "Summary\tOwner\nThing\tana\n"
    draft = drafts_for(text)[0]
    assert (draft.title, draft.assignee) == ("Thing", "ana")


def test_utf8_bom_is_stripped_from_the_first_header():
    columns, _ = read_csv("﻿Summary,Owner\nThing,ana\n".encode())
    assert columns[0] == "Summary"


def test_blank_rows_are_skipped():
    text = "Summary,Owner\nThing,ana\n,\n\n"
    assert len(drafts_for(text)) == 1


def test_empty_file_is_a_provider_error():
    with pytest.raises(ProviderError, match="empty"):
        drafts_for("   ")


def test_missing_file_is_a_provider_error():
    with pytest.raises(ProviderError, match="no CSV file"):
        CsvSource().fetch({})


def test_describe_reports_columns_and_mapping():
    meta = CsvSource().describe({"file": upload()})

    assert meta["row_count"] == 2
    assert "Summary" in meta["columns"]
    assert meta["mapping"]["title"] == "Summary"
    assert "criticality" in meta["mappable_fields"]


def test_source_never_touches_the_database():
    """A source must not be able to write — commit is the only door."""
    src = CsvSource()
    assert not hasattr(src, "db")
    assert all(not n.startswith("save") and not n.startswith("commit") for n in dir(src))
