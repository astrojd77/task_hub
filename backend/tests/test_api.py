from __future__ import annotations


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "://" not in body["db_dialect"]  # credentials must never leak


def test_enums_catalog(client):
    body = client.get("/api/enums").json()
    assert body["status"] == ["todo", "in_progress", "blocked", "done"]
    assert body["impact_size"] == ["xs", "s", "m", "l", "xl"]


def test_providers_lists_local_destination(client):
    body = client.get("/api/providers").json()
    ids = [d["id"] for d in body["destinations"]]
    assert "local" in ids
    local = next(d for d in body["destinations"] if d["id"] == "local")
    assert local["capabilities"] == {"create": True, "update": True, "close": True}


def test_commit_endpoint_round_trip(client):
    payload = {
        "drafts": [
            {
                "title": "Patch the auth service",
                "source_provider": "csv",
                "source_ref": "row-1",
                "due_date": "2026-08-15",
                "criticality": "high",
                "impact_size": "l",
            }
        ]
    }
    result = client.post("/api/commit", json=payload).json()
    assert result["created"] == 1

    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Patch the auth service"
    assert tasks[0]["criticality"] == "high"


def test_commit_rejects_blank_title_with_422(client):
    payload = {"drafts": [{"title": "  ", "source_provider": "csv", "source_ref": "r"}]}
    assert client.post("/api/commit", json=payload).status_code == 422


def test_commit_rejects_off_scale_enum_with_422(client):
    payload = {
        "drafts": [{"title": "x", "source_provider": "csv", "source_ref": "r", "priority": "p0"}]
    }
    assert client.post("/api/commit", json=payload).status_code == 422


def test_task_filters(client):
    drafts = [
        {
            "title": "A",
            "source_provider": "csv",
            "source_ref": "a",
            "project": "Platform",
            "status": "blocked",
        },
        {
            "title": "B",
            "source_provider": "csv",
            "source_ref": "b",
            "project": "Billing",
            "status": "todo",
        },
    ]
    client.post("/api/commit", json={"drafts": drafts})

    assert len(client.get("/api/tasks", params={"project": "Platform"}).json()) == 1
    assert len(client.get("/api/tasks", params={"status": "blocked"}).json()) == 1
    assert len(client.get("/api/tasks", params={"q": "b"}).json()) == 1
    assert len(client.get("/api/tasks", params={"source": "jira"}).json()) == 0

    facets = client.get("/api/tasks/facets").json()
    assert sorted(facets["project"]) == ["Billing", "Platform"]


def test_task_detail_and_delete(client):
    payload = {"drafts": [{"title": "A", "source_provider": "csv", "source_ref": "a"}]}
    task_id = client.post("/api/commit", json=payload).json()["tasks"][0]["id"]

    assert client.get(f"/api/tasks/{task_id}").json()["title"] == "A"
    assert client.delete(f"/api/tasks/{task_id}").status_code == 204
    assert client.get(f"/api/tasks/{task_id}").status_code == 404


def test_ready_checks_the_database(client):
    assert client.get("/api/ready").json() == {"status": "ready"}


def test_spa_is_not_mounted_without_a_build(client):
    """In dev Vite serves the frontend; the API must not invent an index.html."""
    from app.main import serving_spa

    assert serving_spa is False


def test_unknown_api_path_404s_as_an_api_path(client):
    res = client.get("/api/nonexistent")
    assert res.status_code == 404


# -- watch view ----------------------------------------------------------


def _commit(client, **overrides):
    draft = {
        "title": "t",
        "source_provider": "csv",
        "source_ref": overrides.pop("source_ref", "r1"),
    } | overrides
    return client.post("/api/commit", json={"drafts": [draft]}).json()


def test_watch_sections_and_scores(client):
    _commit(
        client,
        source_ref="worst",
        title="Cert expired",
        criticality="critical",
        impact_size="xl",
        due_date="2026-07-20",
    )
    _commit(client, source_ref="calm", title="Tidy docs", due_date="2026-12-01")
    _commit(client, source_ref="stuck", title="Waiting on vendor", status="blocked")

    body = client.get("/api/watch", params={"today": "2026-07-26"}).json()
    sections = {s["key"]: s for s in body["sections"]}

    assert body["today"] == "2026-07-26"
    assert body["weights"]["overdue"] == 5

    overdue = sections["overdue"]["items"]
    assert [i["task"]["title"] for i in overdue] == ["Cert expired"]
    assert overdue[0]["score"] == 5 + 4 + 5
    assert any("overdue" in r for r in overdue[0]["reasons"])

    assert [i["task"]["title"] for i in sections["blocked"]["items"]] == ["Waiting on vendor"]
    assert [i["task"]["title"] for i in sections["keep_an_eye_on"]["items"]] == ["Cert expired"]
    # Far-future work belongs to no section.
    assert all(
        "Tidy docs" not in [i["task"]["title"] for i in s["items"]] for s in body["sections"]
    )


def test_watch_excludes_done_work(client):
    _commit(
        client,
        source_ref="finished",
        status="done",
        criticality="critical",
        due_date="2026-01-01",
    )

    body = client.get("/api/watch", params={"today": "2026-07-26"}).json()
    assert all(s["items"] == [] for s in body["sections"])


def test_watch_sorts_by_score_descending(client):
    _commit(client, source_ref="a", title="Low", criticality="low", due_date="2026-07-20")
    _commit(
        client,
        source_ref="b",
        title="High",
        criticality="critical",
        impact_size="xl",
        due_date="2026-07-20",
    )

    items = client.get("/api/watch", params={"today": "2026-07-26"}).json()
    overdue = next(s for s in items["sections"] if s["key"] == "overdue")["items"]

    assert [i["task"]["title"] for i in overdue] == ["High", "Low"]
    assert overdue[0]["score"] > overdue[1]["score"]


def test_watch_honours_the_shared_filters(client):
    _commit(client, source_ref="p1", project="Platform", criticality="critical")
    _commit(client, source_ref="p2", project="Billing", criticality="critical")

    body = client.get("/api/watch", params={"today": "2026-07-26", "project": "Platform"}).json()
    eye = next(s for s in body["sections"] if s["key"] == "keep_an_eye_on")["items"]

    assert len(eye) == 1
    assert eye[0]["task"]["project"] == "Platform"


# -- routing endpoints ---------------------------------------------------


def test_project_default_route_round_trip(client):
    res = client.put("/api/routes", json={"project": "Platform", "destination": "local"})
    assert res.status_code == 200
    assert client.get("/api/routes").json() == [{"project": "Platform", "destination": "local"}]

    client.put("/api/routes", json={"project": "Platform", "destination": None})
    assert client.get("/api/routes").json() == []


def test_route_to_unknown_destination_is_400(client):
    res = client.put("/api/routes", json={"project": "P", "destination": "myspace"})
    assert res.status_code == 400


def test_destination_resolution_explains_itself(client):
    task_id = _commit(client, source_ref="r", project="Platform")["tasks"][0]["id"]

    assert client.get(f"/api/tasks/{task_id}/destination").json()["reason"] == "set on the task"

    # Commit defaults destination to "local"; clear it to see the fallthrough.
    client.put(f"/api/tasks/{task_id}/destination", json={"destination": None})
    client.put("/api/routes", json={"project": "Platform", "destination": "local"})

    body = client.get(f"/api/tasks/{task_id}/destination").json()
    assert body["explicit"] is None
    assert body["resolved"] == "local"


def test_push_to_local_records_an_external_ref(client):
    task_id = _commit(client, source_ref="r")["tasks"][0]["id"]

    body = client.post(f"/api/tasks/{task_id}/push").json()
    assert body["action"] == "created"
    assert body["destination"] == "local"
    assert body["task"]["external_refs"] == {"local": task_id}


def test_pushing_a_jira_task_back_to_jira_is_409(client, monkeypatch):
    """The phase 6 guardrail, surfaced as a conflict rather than a 500."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "enabled_destinations", ["local", "jira"], raising=False)

    task_id = _commit(client, source_provider="jira", source_ref="OPS-1")["tasks"][0]["id"]
    client.put(f"/api/tasks/{task_id}/destination", json={"destination": "jira"})

    res = client.post(f"/api/tasks/{task_id}/push")
    assert res.status_code == 409
    assert "duplicate" in res.json()["detail"]


def test_push_of_a_missing_task_is_404(client):
    assert client.post("/api/tasks/nope/push").status_code == 404
