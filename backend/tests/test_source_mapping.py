"""Per-source field and value mapping, across all three inbound adapters.

The point of this layer is that every flow becomes configurable in the same
way, and that configuration is always an *override* — an unconfigured install
still imports sensibly.
"""

from __future__ import annotations

import json
from datetime import date

from app.providers.base import UploadedFile
from app.providers.sources.csv_source import CsvSource
from app.providers.sources.email_source import EmailSource
from app.providers.sources.jira_source import JiraSource
from app.services.source_mapping import (
    MAPPING_CONFIG_KEY,
    resolve,
    set_mapping,
    translate_enum,
)
from tests.test_jira_source import FakeClient, issue

CSV = (
    "Ticket,Headline,Notes,Workflow,Sev,Blast,Deadline\n"
    "OPS-1,Rotate cert,Expires soon,Doing,Sev 1,Massive,2026-08-01\n"
)

EML = (
    "Message-ID: <m1@example.com>\n"
    "From: Ana <ana@example.com>\n"
    "Subject: Contract renewal\n"
    "Content-Type: text/plain; charset=utf-8\n"
    "\n"
    "Body text here.\n"
)


def with_mapping(db, source_provider, config=None):
    return {**(config or {}), MAPPING_CONFIG_KEY: resolve(db, source_provider)}


# -- resolution ----------------------------------------------------------


def test_an_unconfigured_source_resolves_to_an_empty_mapping(db):
    mapping = resolve(db, "csv")

    assert mapping.fields == {}
    assert mapping.input_for("summary", "Summary") == "Summary"  # falls back
    assert mapping.translate("criticality", "Sev 1") == (None, False)


def test_value_keys_are_lowercased_so_matching_is_case_insensitive(db):
    set_mapping(db, "csv", "criticality", "Sev", {"SEV 1": "critical"})

    assert resolve(db, "csv").translate("criticality", "sev 1") == ("critical", True)
    assert resolve(db, "csv").translate("criticality", "Sev 1") == ("critical", True)


def test_clearing_both_halves_removes_the_row(db):
    set_mapping(db, "csv", "criticality", "Sev", {"sev 1": "critical"})
    assert set_mapping(db, "csv", "criticality", None, {}) is None
    assert resolve(db, "csv").fields == {}


def test_translate_enum_prefers_configuration_over_the_adapter_table(db):
    set_mapping(db, "csv", "criticality", None, {"spicy": "critical"})
    mapping = resolve(db, "csv")
    warnings: list[str] = []

    # Configured rule wins.
    assert (
        translate_enum(mapping, "criticality", "spicy", {}, "criticality", warnings) == "critical"
    )
    # No rule -> the adapter's own table still applies.
    assert (
        translate_enum(mapping, "criticality", "sev 1", {"sev 1": "critical"}, "c", warnings)
        == "critical"
    )
    assert warnings == []


def test_an_unmappable_value_warns_rather_than_guessing(db):
    mapping = resolve(db, "csv")
    warnings: list[str] = []

    assert translate_enum(mapping, "criticality", "banana", {}, "criticality", warnings) is None
    assert any("not on the scale" in w for w in warnings)


# -- CSV -----------------------------------------------------------------


def test_csv_uses_the_saved_mapping_when_the_request_supplies_none(db):
    """A recurring import becomes one click once the mapping is saved."""
    for field_key, column in {
        "summary": "Headline",
        "description": "Notes",
        "due_date": "Deadline",
        "source_ref": "Ticket",
    }.items():
        set_mapping(db, "csv", field_key, column)

    src = CsvSource()
    config = with_mapping(db, "csv", {"file": UploadedFile("t.csv", CSV.encode())})
    draft = src.to_draft(src.fetch(config)[0])

    assert draft.summary == "Rotate cert"
    assert draft.description == "Expires soon"
    assert draft.due_date == date(2026, 8, 1)
    assert draft.source_ref == "OPS-1"


def test_csv_value_rules_translate_a_house_vocabulary(db):
    set_mapping(db, "csv", "summary", "Headline")
    set_mapping(db, "csv", "criticality", "Sev", {"sev 1": "critical"})
    set_mapping(db, "csv", "impact_size", "Blast", {"massive": "xl"})
    set_mapping(db, "csv", "status", "Workflow", {"doing": "in_progress"})

    src = CsvSource()
    config = with_mapping(db, "csv", {"file": UploadedFile("t.csv", CSV.encode())})
    draft = src.to_draft(src.fetch(config)[0])

    assert draft.criticality == "critical"
    assert draft.impact_size == "xl"
    assert draft.status == "in_progress"


def test_a_request_mapping_still_beats_the_saved_one(db):
    """Remapping a column in the import screen must take effect immediately."""
    set_mapping(db, "csv", "summary", "Notes")

    src = CsvSource()
    config = with_mapping(
        db, "csv", {"file": UploadedFile("t.csv", CSV.encode()), "mapping": {"summary": "Headline"}}
    )
    assert src.to_draft(src.fetch(config)[0]).summary == "Rotate cert"


def test_csv_feeds_a_custom_field_from_a_mapped_column(db):
    set_mapping(db, "csv", "summary", "Headline")
    set_mapping(db, "csv", "type", "Workflow", {"doing": "bug"})

    src = CsvSource()
    config = with_mapping(db, "csv", {"file": UploadedFile("t.csv", CSV.encode())})
    draft = src.to_draft(src.fetch(config)[0])

    assert draft.custom_fields == {"type": "bug"}


def test_csv_reports_its_columns_as_mappable_inputs():
    inputs = CsvSource().mappable_inputs({"file": UploadedFile("t.csv", CSV.encode())})

    assert [i["key"] for i in inputs][:3] == ["Ticket", "Headline", "Notes"]
    # A sample value makes the right choice obvious in the UI.
    assert inputs[1]["hint"] == "Rotate cert"


def test_csv_inputs_without_a_file_are_empty_not_an_error():
    assert CsvSource().mappable_inputs({}) == []


# -- email ---------------------------------------------------------------


def test_email_defaults_map_subject_and_body(db):
    src = EmailSource()
    config = with_mapping(db, "email", {"file": UploadedFile("n.eml", EML.encode())})
    draft = src.to_draft(src.fetch(config)[0])

    assert draft.summary == "Contract renewal"
    assert draft.description == "Body text here."


def test_email_parts_can_be_remapped(db):
    """A team whose convention differs should not need a code change."""
    set_mapping(db, "email", "summary", "from")
    set_mapping(db, "email", "description", "subject")

    src = EmailSource()
    config = with_mapping(db, "email", {"file": UploadedFile("n.eml", EML.encode())})
    draft = src.to_draft(src.fetch(config)[0])

    assert draft.summary == "Ana <ana@example.com>"
    assert draft.description == "Contract renewal"


def test_email_can_feed_a_custom_field(db):
    set_mapping(db, "email", "platform", "from", {"ana <ana@example.com>": "on_prem"})

    src = EmailSource()
    config = with_mapping(db, "email", {"file": UploadedFile("n.eml", EML.encode())})
    draft = src.to_draft(src.fetch(config)[0])

    assert draft.custom_fields == {"platform": "on_prem"}


def test_email_reports_its_parts_with_samples():
    inputs = EmailSource().mappable_inputs({"file": UploadedFile("n.eml", EML.encode())})
    by_key = {i["key"]: i for i in inputs}

    assert by_key["subject"]["hint"] == "Contract renewal"
    assert by_key["body"]["hint"] == "Body text here."
    assert by_key["from"]["label"] == "Sender"


# -- Jira ----------------------------------------------------------------


def test_jira_defaults_need_no_mapping(db):
    src = JiraSource(client=FakeClient())
    draft = src.to_draft(src.fetch(with_mapping(db, "jira", {"issue_key": "OPS-1"}))[0])

    assert draft.summary == "Rotate signing cert"
    assert draft.status == "in_progress"


def test_jira_fields_can_be_remapped(db):
    """An instance whose real due date lives in a custom field still works."""
    set_mapping(db, "jira", "due_date", "customfield_20001")

    src = JiraSource(client=FakeClient([issue("OPS-1", customfield_20001="2026-12-25")]))
    draft = src.to_draft(src.fetch(with_mapping(db, "jira", {"issue_key": "OPS-1"}))[0])

    assert draft.due_date == date(2026, 12, 25)


def test_a_mapped_jira_field_is_requested_from_the_api(db):
    """Jira does not return a custom field unless you ask for it by name."""
    set_mapping(db, "jira", "criticality", "customfield_10042")

    src = JiraSource(client=FakeClient())
    src.fetch(with_mapping(db, "jira", {"issue_key": "OPS-1"}))

    assert "customfield_10042" in src.client.calls[0][2]


def test_jira_value_rules_extend_the_builtin_table(db):
    set_mapping(db, "jira", "criticality", "customfield_10042", {"escalated": "high"})

    src = JiraSource(client=FakeClient([issue("OPS-1", customfield_10042={"value": "Escalated"})]))
    draft = src.to_draft(src.fetch(with_mapping(db, "jira", {"issue_key": "OPS-1"}))[0])

    assert draft.criticality == "high"
    assert not any("not on the scale" in w for w in draft.warnings)


def test_jira_status_rules_cover_a_bespoke_workflow(db):
    set_mapping(db, "jira", "status", None, {"pending vendor review": "blocked"})

    src = JiraSource(
        client=FakeClient(
            [
                issue(
                    "OPS-1",
                    status={
                        "name": "Pending Vendor Review",
                        "statusCategory": {"key": "indeterminate"},
                    },
                )
            ]
        )
    )
    draft = src.to_draft(src.fetch(with_mapping(db, "jira", {"issue_key": "OPS-1"}))[0])

    assert draft.status == "blocked"
    assert draft.warnings == []


def test_jira_can_feed_a_custom_field(db):
    set_mapping(db, "jira", "type", "customfield_30001", {"defect": "bug"})

    src = JiraSource(client=FakeClient([issue("OPS-1", customfield_30001={"value": "Defect"})]))
    draft = src.to_draft(src.fetch(with_mapping(db, "jira", {"issue_key": "OPS-1"}))[0])

    assert draft.custom_fields == {"type": "bug"}


def test_jira_offers_its_stock_fields_without_a_connection(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "jira_base_url", "", raising=False)
    keys = [i["key"] for i in JiraSource().mappable_inputs({})]

    assert "summary" in keys and "duedate" in keys


# -- API -----------------------------------------------------------------


def test_mapping_round_trip_through_the_api(client):
    res = client.put(
        "/api/config/mappings",
        json={
            "source_provider": "csv",
            "mappings": {
                "summary": {"source_expr": "Headline", "value_map": {}},
                "criticality": {"source_expr": "Sev", "value_map": {"Sev 1": "critical"}},
            },
        },
    )
    assert res.status_code == 200

    saved = {m["field_key"]: m for m in client.get("/api/config").json()["mappings"]}
    assert saved["summary"]["source_expr"] == "Headline"
    assert saved["criticality"]["value_map"] == {"sev 1": "critical"}


def test_saved_mapping_drives_a_real_import(client):
    client.put(
        "/api/config/mappings",
        json={
            "source_provider": "csv",
            "mappings": {
                "summary": {"source_expr": "Headline"},
                "criticality": {"source_expr": "Sev", "value_map": {"Sev 1": "critical"}},
                "source_ref": {"source_expr": "Ticket"},
            },
        },
    )

    body = client.post(
        "/api/sources/csv/drafts",
        files={"file": ("t.csv", CSV.encode(), "text/csv")},
        data={"config": json.dumps({})},
    ).json()

    draft = body["drafts"][0]
    assert draft["summary"] == "Rotate cert"
    assert draft["criticality"] == "critical"
    assert draft["source_ref"] == "OPS-1"


def test_inputs_endpoint_lists_csv_columns(client):
    res = client.post(
        "/api/sources/csv/inputs",
        files={"file": ("t.csv", CSV.encode(), "text/csv")},
        data={"config": "{}"},
    )

    assert res.status_code == 200
    assert [i["key"] for i in res.json()][:2] == ["Ticket", "Headline"]


def test_inputs_endpoint_lists_email_parts(client):
    res = client.post(
        "/api/sources/email/inputs",
        files={"file": ("n.eml", EML.encode(), "message/rfc822")},
        data={"config": "{}"},
    )

    assert {i["key"] for i in res.json()} >= {"subject", "body", "from"}


def test_mapping_for_an_unknown_source_is_404(client):
    res = client.put(
        "/api/config/mappings",
        json={"source_provider": "telepathy", "mappings": {}},
    )
    assert res.status_code == 404
