"""The phase 1 milestone, end to end.

Import a CSV, review/edit, commit, see tasks; re-import the same file and get
no duplicates.
"""

from __future__ import annotations

import json

SAMPLE = (
    "Summary,State,Urgency,Due Date,Owner,Workstream\n"
    "Rotate signing cert,In Progress,P1,2026-08-01,ana,Platform\n"
    "Upgrade node pool,Blocked,low,2026-09-15,raj,Platform\n"
)


def post_csv(client, text: str = SAMPLE, config: dict | None = None):
    return client.post(
        "/api/sources/csv/drafts",
        files={"file": ("tasks.csv", text.encode("utf-8"), "text/csv")},
        data={"config": json.dumps(config or {})},
    )


def test_csv_is_a_registered_source(client):
    ids = [s["id"] for s in client.get("/api/providers").json()["sources"]]
    assert "csv" in ids


def test_drafts_endpoint_parses_without_persisting(client):
    body = post_csv(client).json()

    assert body["source_provider"] == "csv"
    assert len(body["drafts"]) == 2
    assert body["meta"]["mapping"]["title"] == "Summary"
    # Nothing has been committed.
    assert client.get("/api/tasks").json() == []


def test_full_milestone_import_review_commit_reimport(client):
    drafts = post_csv(client).json()["drafts"]

    # The reviewer fills in what the CSV could not supply.
    drafts[0]["criticality"] = "critical"
    drafts[0]["impact_size"] = "xl"
    drafts[1]["criticality"] = "low"
    drafts[1]["impact_size"] = "s"

    result = client.post("/api/commit", json={"drafts": drafts}).json()
    assert (result["created"], result["updated"]) == (2, 0)

    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 2
    assert {t["title"] for t in tasks} == {"Rotate signing cert", "Upgrade node pool"}
    assert {t["criticality"] for t in tasks} == {"critical", "low"}

    # Re-import the same file: still two tasks, now updates rather than creates.
    again = client.post("/api/commit", json={"drafts": post_csv(client).json()["drafts"]}).json()
    assert (again["created"], again["updated"]) == (0, 2)
    assert len(client.get("/api/tasks").json()) == 2


def test_reimport_prefills_reviewed_fields_and_says_so(client):
    drafts = post_csv(client).json()["drafts"]
    drafts[0]["criticality"] = "critical"
    drafts[0]["impact_size"] = "xl"
    client.post("/api/commit", json={"drafts": drafts})

    reimported = post_csv(client).json()["drafts"]
    first = next(d for d in reimported if d["title"] == "Rotate signing cert")

    assert first["existing_task_id"] is not None
    assert first["criticality"] == "critical"
    assert first["impact_size"] == "xl"
    assert any("already imported" in w for w in first["warnings"])


def test_source_supplied_fields_win_over_the_previous_import(client):
    """The source is authoritative for what it knows; review-only fields persist.

    Needs a stable id column — a row-hash ref would change with the row and the
    re-import would be a different item entirely.
    """
    keyed = "Key,Summary,State\nOPS-1,Rotate signing cert,In Progress\n"
    drafts = post_csv(client, keyed).json()["drafts"]
    drafts[0]["criticality"] = "critical"
    client.post("/api/commit", json={"drafts": drafts})

    upstream_changed = "Key,Summary,State\nOPS-1,Rotate signing cert,Blocked\n"
    reimported = post_csv(client, upstream_changed).json()["drafts"][0]

    assert reimported["existing_task_id"] is not None
    assert reimported["status"] == "blocked"  # source wins on what it knows
    assert reimported["criticality"] == "critical"  # review work is preserved


def test_changed_row_without_an_id_column_is_a_new_item(client):
    """Row-hash refs are content-addressed — that is the documented trade-off."""
    client.post("/api/commit", json={"drafts": post_csv(client).json()["drafts"]})

    edited = SAMPLE.replace("Rotate signing cert", "Rotate signing certificate")
    reimported = post_csv(client, edited).json()["drafts"]
    changed = next(d for d in reimported if "certificate" in d["title"])

    assert changed["existing_task_id"] is None


def test_partial_selection_only_commits_chosen_rows(client):
    drafts = post_csv(client).json()["drafts"]

    result = client.post("/api/commit", json={"drafts": drafts[:1]}).json()
    assert result["created"] == 1
    assert len(client.get("/api/tasks").json()) == 1


def test_committing_a_draft_with_no_title_is_rejected(client):
    drafts = post_csv(client, "Summary,Owner\n,ana\n").json()["drafts"]
    assert drafts[0]["title"] == ""

    assert client.post("/api/commit", json={"drafts": drafts}).status_code == 422
    assert client.get("/api/tasks").json() == []


def test_explicit_mapping_is_honoured_by_the_endpoint(client):
    text = "alpha,beta\nfirst,second\n"
    body = post_csv(client, text, {"mapping": {"title": "beta"}}).json()

    assert body["drafts"][0]["title"] == "second"


def test_unknown_source_is_404(client):
    res = client.post(
        "/api/sources/telepathy/drafts",
        files={"file": ("x.csv", b"a\n1\n", "text/csv")},
        data={"config": "{}"},
    )
    assert res.status_code == 404


def test_disabled_source_is_404(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "enabled_sources", [], raising=False)
    assert post_csv(client).status_code == 404


def test_bad_file_is_400_with_the_reason(client):
    res = post_csv(client, "   ")
    assert res.status_code == 400
    assert "empty" in res.json()["detail"]


def test_bad_config_json_is_422(client):
    res = client.post(
        "/api/sources/csv/drafts",
        files={"file": ("tasks.csv", SAMPLE.encode(), "text/csv")},
        data={"config": "{not json"},
    )
    assert res.status_code == 422
