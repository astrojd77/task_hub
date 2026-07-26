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
        "drafts": [
            {"title": "x", "source_provider": "csv", "source_ref": "r", "priority": "p0"}
        ]
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
