"""Jira source: targeting rules and vocabulary translation. No network."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.config import get_settings
from app.providers.base import ProviderError
from app.providers.jira_client import adf_to_text, text_to_adf
from app.providers.sources.jira_source import JiraSource, map_priority, map_status


def issue(key: str = "OPS-1", **field_overrides) -> dict:
    fields = {
        "summary": "Rotate signing cert",
        "description": None,
        "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
        "priority": {"name": "High"},
        "duedate": "2026-08-01",
        "assignee": {"displayName": "Ana Ruiz"},
        "project": {"key": "OPS", "name": "Platform Ops"},
        "labels": ["security"],
        "issuetype": {"name": "Task"},
    }
    fields.update(field_overrides)
    return {"key": key, "fields": fields}


class FakeClient:
    """Stands in for JiraClient so tests never touch the network."""

    def __init__(self, issues: list[dict] | None = None):
        self.issues = issues or [issue()]
        self.calls: list[tuple] = []

    def get_issue(self, key, extra_fields=()):
        self.calls.append(("get_issue", key, extra_fields))
        found = next((i for i in self.issues if i["key"] == key), None)
        if found is None:
            raise ProviderError("Jira returned 404 — check the issue key or the base URL")
        return found

    def search(self, jql, extra_fields=(), limit=100):
        self.calls.append(("search", jql, extra_fields, limit))
        return self.issues[:limit]


def src(issues=None) -> JiraSource:
    return JiraSource(client=FakeClient(issues))


# -- targeting -----------------------------------------------------------


def test_fetch_by_issue_key():
    source = src()
    items = source.fetch({"issue_key": "OPS-1"})

    assert [i.source_ref for i in items] == ["OPS-1"]


def test_issue_key_is_upcased():
    source = src()
    source.fetch({"issue_key": "ops-1"})
    assert source.client.calls[0][1] == "OPS-1"


def test_fetch_by_jql():
    source = src([issue("OPS-1"), issue("OPS-2")])
    items = source.fetch({"jql": "project = OPS AND status != Done"})

    assert [i.source_ref for i in items] == ["OPS-1", "OPS-2"]


def test_neither_key_nor_jql_is_an_error():
    with pytest.raises(ProviderError, match="issue key or a JQL"):
        src().fetch({})


def test_both_key_and_jql_is_an_error():
    """Targeted means one target — never a blanket pull."""
    with pytest.raises(ProviderError, match="not both"):
        src().fetch({"issue_key": "OPS-1", "jql": "project = OPS"})


def test_malformed_issue_key_is_rejected_before_any_call():
    source = src()
    with pytest.raises(ProviderError, match="does not look like"):
        source.fetch({"issue_key": "not a key"})
    assert source.client.calls == []


def test_jql_limit_is_passed_through():
    source = src([issue(f"OPS-{n}") for n in range(1, 6)])
    source.fetch({"jql": "project = OPS", "limit": 2})
    assert source.client.calls[0][3] == 2


# -- translation ---------------------------------------------------------


def test_draft_carries_the_canonical_shape():
    source = src()
    draft = source.to_draft(source.fetch({"issue_key": "OPS-1"})[0])

    assert draft.title == "Rotate signing cert"
    assert draft.status == "in_progress"
    assert draft.priority == "high"
    assert draft.due_date == date(2026, 8, 1)
    assert draft.assignee == "Ana Ruiz"
    assert draft.project == "Platform Ops"
    assert draft.labels == ["security"]
    assert draft.source_provider == "jira"
    assert draft.source_ref == "OPS-1"
    # Provenance is kept whole.
    assert draft.raw_payload["fields"]["issuetype"]["name"] == "Task"


def test_status_name_mapping():
    assert map_status({"name": "Blocked"})[0] == "blocked"
    assert map_status({"name": "Done"})[0] == "done"
    assert map_status({"name": "Backlog"})[0] == "todo"


def test_unknown_status_falls_back_to_the_jira_category_and_says_so():
    mapped, warning = map_status(
        {"name": "Pending Vendor Review", "statusCategory": {"key": "indeterminate"}}
    )
    assert mapped == "in_progress"
    assert "category" in warning


def test_status_with_no_recognisable_signal_defaults_and_warns():
    mapped, warning = map_status({"name": "Zorb", "statusCategory": {"key": "weird"}})
    assert mapped == "todo"
    assert "did not map" in warning


def test_priority_mapping_and_fallback():
    assert map_priority({"name": "Highest"})[0] == "urgent"
    assert map_priority({"name": "Lowest"})[0] == "low"

    mapped, warning = map_priority({"name": "Spicy"})
    assert mapped == "medium"
    assert "did not map" in warning


def test_missing_priority_is_medium_without_a_warning():
    assert map_priority(None) == ("medium", None)


# -- criticality / impact custom fields ----------------------------------


def test_criticality_and_impact_are_blank_when_no_field_is_configured(monkeypatch):
    """The normal case: Jira has no such field, so the review popup asks."""
    settings = get_settings()
    monkeypatch.setattr(settings, "jira_criticality_field", "", raising=False)
    monkeypatch.setattr(settings, "jira_impact_field", "", raising=False)

    source = src()
    draft = source.to_draft(source.fetch({"issue_key": "OPS-1"})[0])

    assert draft.criticality is None
    assert draft.impact_size is None
    assert draft.warnings == []


def test_configured_custom_fields_map_into_the_canonical_scales(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "jira_criticality_field", "customfield_10042", raising=False)
    monkeypatch.setattr(settings, "jira_impact_field", "customfield_10043", raising=False)

    source = src(
        [issue("OPS-1", customfield_10042={"value": "Sev 1"}, customfield_10043={"value": "XL"})]
    )
    draft = source.to_draft(source.fetch({"issue_key": "OPS-1"})[0])

    assert draft.criticality == "critical"
    assert draft.impact_size == "xl"


def test_custom_field_shapes_are_all_handled(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "jira_criticality_field", "cf", raising=False)
    monkeypatch.setattr(settings, "jira_impact_field", "", raising=False)

    for raw in ("High", {"value": "High"}, {"name": "High"}, [{"value": "High"}]):
        source = src([issue("OPS-1", cf=raw)])
        draft = source.to_draft(source.fetch({"issue_key": "OPS-1"})[0])
        assert draft.criticality == "high", raw


def test_configured_but_empty_field_warns(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "jira_criticality_field", "cf", raising=False)
    monkeypatch.setattr(settings, "jira_impact_field", "", raising=False)

    source = src([issue("OPS-1", cf=None)])
    draft = source.to_draft(source.fetch({"issue_key": "OPS-1"})[0])

    assert draft.criticality is None
    assert any("is empty on this issue" in w for w in draft.warnings)


def test_off_scale_custom_field_value_warns(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "jira_criticality_field", "cf", raising=False)
    monkeypatch.setattr(settings, "jira_impact_field", "", raising=False)

    source = src([issue("OPS-1", cf={"value": "Apocalyptic"})])
    draft = source.to_draft(source.fetch({"issue_key": "OPS-1"})[0])

    assert draft.criticality is None
    assert any("not on the scale" in w for w in draft.warnings)


def test_requested_fields_include_the_configured_custom_fields(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "jira_criticality_field", "cf_crit", raising=False)
    monkeypatch.setattr(settings, "jira_impact_field", "cf_imp", raising=False)

    source = src()
    source.fetch({"issue_key": "OPS-1"})

    assert source.client.calls[0][2] == ("cf_crit", "cf_imp")


# -- ADF -----------------------------------------------------------------


def test_adf_is_flattened_to_readable_text():
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "First line."}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "Second line."}]},
        ],
    }
    assert adf_to_text(doc) == "First line.\nSecond line."


def test_adf_handles_plain_strings_and_none():
    assert adf_to_text("already text") == "already text"
    assert adf_to_text(None) is None
    assert adf_to_text({"type": "doc", "content": []}) is None


def test_text_to_adf_round_trips():
    assert adf_to_text(text_to_adf("Hello\nWorld")) == "Hello\nWorld"


# -- review style --------------------------------------------------------


def test_single_issue_gets_a_modal_and_a_query_gets_a_table():
    """Phase 4's UI rule, decided by the adapter that knows the shape."""
    assert src().describe({"issue_key": "OPS-1"})["review_style"] == "modal"
    assert src().describe({"jql": "project = OPS"})["review_style"] == "table"
