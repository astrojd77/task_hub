"""Configurable dropdowns and per-source defaults."""

from __future__ import annotations

import json

import pytest

from app.schemas.task import DraftTask
from app.services.field_config import (
    FieldConfigError,
    apply_defaults,
    delete_field,
    ensure_builtin_fields,
    list_fields,
    set_default,
    upsert_field,
    validate_custom_fields,
)


def draft(**overrides) -> DraftTask:
    base = {"summary": "t", "source_provider": "csv", "source_ref": "r1"}
    return DraftTask(**(base | overrides))


# -- seeding -------------------------------------------------------------


def test_builtin_fields_seed_from_the_canonical_enums(db):
    fields = {f.field_key: f for f in ensure_builtin_fields(db)}

    assert set(fields) == {"status", "priority", "criticality", "impact_size"}
    assert fields["impact_size"].values == ["xs", "s", "m", "l", "xl"]
    assert fields["criticality"].label == "Criticality"
    assert all(f.kind == "builtin" for f in fields.values())


def test_seeding_is_idempotent(db):
    ensure_builtin_fields(db)
    ensure_builtin_fields(db)

    assert len(list_fields(db)) == 4


# -- custom fields -------------------------------------------------------


def test_a_custom_field_needs_no_migration(db):
    field = upsert_field(
        db,
        field_key="type",
        label="Type",
        options=[{"value": "bug", "label": "Bug"}, {"value": "feature", "label": "Feature"}],
    )

    assert field.kind == "custom"
    assert field.values == ["bug", "feature"]


def test_field_key_is_normalised(db):
    field = upsert_field(db, field_key="  Blast Radius ", label="Blast", options=[{"value": "a"}])
    assert field.field_key == "blast_radius"


def test_option_label_defaults_to_its_value(db):
    field = upsert_field(db, field_key="platform", label="Platform", options=[{"value": "aws"}])
    assert field.options == [{"value": "aws", "label": "aws"}]


def test_duplicate_and_blank_options_are_rejected(db):
    with pytest.raises(FieldConfigError, match="duplicate"):
        upsert_field(db, field_key="t", label="T", options=[{"value": "a"}, {"value": "a"}])

    with pytest.raises(FieldConfigError, match="blank"):
        upsert_field(db, field_key="t", label="T", options=[{"value": "   "}])


def test_updating_a_field_replaces_its_options(db):
    upsert_field(db, field_key="type", label="Type", options=[{"value": "bug"}])
    field = upsert_field(db, field_key="type", label="Work type", options=[{"value": "chore"}])

    assert field.label == "Work type"
    assert field.values == ["chore"]


def test_a_custom_field_can_be_deleted(db):
    upsert_field(db, field_key="type", label="Type", options=[{"value": "bug"}])
    delete_field(db, "type")

    assert [f.field_key for f in list_fields(db)] == []


# -- builtin scales are constrained --------------------------------------


def test_builtin_options_can_be_relabelled_reordered_and_subset(db):
    ensure_builtin_fields(db)

    field = upsert_field(
        db,
        field_key="criticality",
        label="Severity",
        options=[
            {"value": "critical", "label": "Sev 1"},
            {"value": "high", "label": "Sev 2"},
        ],
    )

    assert field.label == "Severity"
    assert field.values == ["critical", "high"]
    assert field.options[0]["label"] == "Sev 1"


def test_a_new_value_cannot_be_invented_on_a_builtin_scale(db):
    """The watch weights and every adapter's mapping table key off these."""
    ensure_builtin_fields(db)

    with pytest.raises(FieldConfigError, match="not canonical"):
        upsert_field(
            db,
            field_key="criticality",
            label="Criticality",
            options=[{"value": "apocalyptic"}],
        )


def test_a_builtin_scale_cannot_be_emptied(db):
    ensure_builtin_fields(db)

    with pytest.raises(FieldConfigError, match="at least one option"):
        upsert_field(db, field_key="status", label="Status", options=[])


def test_a_builtin_field_cannot_be_deleted(db):
    ensure_builtin_fields(db)

    with pytest.raises(FieldConfigError, match="cannot be deleted"):
        delete_field(db, "status")


# -- validation ----------------------------------------------------------


def test_custom_field_values_are_validated_against_the_options(db):
    upsert_field(db, field_key="type", label="Type", options=[{"value": "bug"}])

    assert validate_custom_fields(db, {"type": "bug"}) == []
    assert validate_custom_fields(db, {"type": "banana"}) != []


def test_an_unknown_custom_field_is_rejected(db):
    errors = validate_custom_fields(db, {"nonsense": "x"})
    assert any("unknown custom field" in e for e in errors)


def test_a_required_custom_field_blocks_commit(db):
    upsert_field(db, field_key="type", label="Type", options=[{"value": "bug"}], is_required=True)

    assert any("required" in e for e in validate_custom_fields(db, {}))
    assert validate_custom_fields(db, {"type": "bug"}) == []


def test_a_disabled_required_field_does_not_block(db):
    upsert_field(
        db,
        field_key="type",
        label="Type",
        options=[{"value": "bug"}],
        is_required=True,
        enabled=False,
    )

    assert validate_custom_fields(db, {}) == []


# -- per-source defaults -------------------------------------------------


def test_defaults_fill_only_what_the_source_left_blank(db):
    ensure_builtin_fields(db)
    set_default(db, "email", "criticality", "high")
    set_default(db, "email", "impact_size", "l")

    drafts = [draft(source_provider="email"), draft(source_provider="email", criticality="low")]
    apply_defaults(db, drafts, "email")

    assert drafts[0].criticality == "high"
    assert drafts[0].impact_size == "l"
    # The source knew this one; a default must never overwrite it.
    assert drafts[1].criticality == "low"


def test_defaults_are_announced_in_the_warnings(db):
    ensure_builtin_fields(db)
    set_default(db, "email", "criticality", "high")

    drafts = [draft(source_provider="email")]
    apply_defaults(db, drafts, "email")

    assert any("defaults applied for email" in w for w in drafts[0].warnings)


def test_defaults_are_per_source(db):
    ensure_builtin_fields(db)
    set_default(db, "email", "criticality", "high")

    drafts = [draft(source_provider="csv")]
    apply_defaults(db, drafts, "csv")

    assert drafts[0].criticality is None


def test_custom_field_defaults_apply(db):
    upsert_field(db, field_key="type", label="Type", options=[{"value": "request"}])
    set_default(db, "email", "type", "request")

    drafts = [draft(source_provider="email")]
    apply_defaults(db, drafts, "email")

    assert drafts[0].custom_fields["type"] == "request"


def test_project_can_be_defaulted_even_though_it_is_not_a_dropdown(db):
    set_default(db, "email", "project", "Legal")

    drafts = [draft(source_provider="email")]
    apply_defaults(db, drafts, "email")

    assert drafts[0].project == "Legal"


def test_a_default_must_be_one_of_the_options(db):
    ensure_builtin_fields(db)

    with pytest.raises(FieldConfigError, match="not an option"):
        set_default(db, "email", "criticality", "banana")


def test_a_default_for_an_unknown_field_is_rejected(db):
    with pytest.raises(FieldConfigError, match="unknown field"):
        set_default(db, "email", "nonsense", "x")


def test_a_default_can_be_cleared(db):
    ensure_builtin_fields(db)
    set_default(db, "email", "criticality", "high")
    assert set_default(db, "email", "criticality", None) is None

    drafts = [draft(source_provider="email")]
    apply_defaults(db, drafts, "email")
    assert drafts[0].criticality is None


def test_a_default_orphaned_by_an_option_removal_is_skipped_not_fatal(db):
    """The option was removed after the default was set."""
    upsert_field(db, field_key="type", label="Type", options=[{"value": "bug"}])
    set_default(db, "csv", "type", "bug")
    upsert_field(db, field_key="type", label="Type", options=[{"value": "chore"}])

    drafts = [draft(source_provider="csv")]
    apply_defaults(db, drafts, "csv")  # must not raise

    # It still pre-fills; commit is where the stale value gets rejected.
    assert drafts[0].custom_fields.get("type") == "bug"
    assert validate_custom_fields(db, drafts[0].custom_fields) != []


def test_deleting_a_field_removes_its_defaults(db):
    upsert_field(db, field_key="type", label="Type", options=[{"value": "bug"}])
    set_default(db, "csv", "type", "bug")
    delete_field(db, "type")

    drafts = [draft(source_provider="csv")]
    apply_defaults(db, drafts, "csv")
    assert drafts[0].custom_fields == {}


# -- API and end-to-end --------------------------------------------------


def test_config_endpoint_seeds_and_lists(client):
    body = client.get("/api/config").json()

    keys = {f["field_key"] for f in body["fields"]}
    assert {"status", "priority", "criticality", "impact_size"} <= keys
    assert "csv" in body["sources"]
    assert all(f["values_locked"] for f in body["fields"] if f["kind"] == "builtin")


def test_enums_endpoint_reflects_a_configured_subset(client):
    client.put(
        "/api/config/fields/criticality",
        json={
            "field_key": "criticality",
            "label": "Severity",
            "options": [{"value": "critical", "label": "Sev 1"}],
        },
    )

    assert client.get("/api/enums").json()["criticality"] == ["critical"]


def test_inventing_a_builtin_value_over_the_api_is_400(client):
    res = client.put(
        "/api/config/fields/criticality",
        json={"field_key": "criticality", "label": "C", "options": [{"value": "apocalyptic"}]},
    )
    assert res.status_code == 400
    assert "not canonical" in res.json()["detail"]


def test_custom_field_round_trip_through_import_and_commit(client):
    client.put(
        "/api/config/fields/type",
        json={
            "field_key": "type",
            "label": "Type",
            "options": [{"value": "bug", "label": "Bug"}, {"value": "chore", "label": "Chore"}],
        },
    )
    client.put(
        "/api/config/defaults",
        json={"source_provider": "csv", "field_key": "type", "value": "chore"},
    )

    batch = client.post(
        "/api/sources/csv/drafts",
        files={"file": ("t.csv", b"Summary\nDo a thing\n", "text/csv")},
        data={"config": json.dumps({})},
    ).json()

    # The default arrived before review, and said so.
    assert batch["drafts"][0]["custom_fields"] == {"type": "chore"}
    assert any("defaults applied" in w for w in batch["drafts"][0]["warnings"])

    # The reviewer changes it, then commits.
    drafts = batch["drafts"]
    drafts[0]["custom_fields"] = {"type": "bug"}
    result = client.post("/api/commit", json={"drafts": drafts}).json()

    assert result["created"] == 1
    assert client.get("/api/tasks").json()[0]["custom_fields"] == {"type": "bug"}


def test_committing_an_off_option_custom_value_is_a_row_error(client):
    client.put(
        "/api/config/fields/type",
        json={"field_key": "type", "label": "Type", "options": [{"value": "bug"}]},
    )

    result = client.post(
        "/api/commit",
        json={
            "drafts": [
                {
                    "summary": "x",
                    "source_provider": "csv",
                    "source_ref": "r",
                    "custom_fields": {"type": "banana"},
                }
            ]
        },
    ).json()

    assert result["created"] == 0
    assert result["errors"]
    assert client.get("/api/tasks").json() == []


def test_default_for_an_unknown_source_is_404(client):
    res = client.put(
        "/api/config/defaults",
        json={"source_provider": "telepathy", "field_key": "project", "value": "x"},
    )
    assert res.status_code == 404
