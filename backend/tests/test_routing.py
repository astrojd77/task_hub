"""Destination routing, the push path, and the loop-back guardrail."""

from __future__ import annotations

import pytest

from app.models.task import Task
from app.providers.base import Capabilities, ExternalRef
from app.providers.registry import registry
from app.services.routing import (
    RoutingError,
    check_push_allowed,
    push_task,
    resolve_destination,
    set_route,
)


def make_task(db, **overrides) -> Task:
    base = {
        "summary": "t",
        "status": "todo",
        "priority": "medium",
        "source_provider": "csv",
        "source_ref": overrides.pop("source_ref", "r1"),
        "labels": [],
        "external_refs": {},
    }
    task = Task(**(base | overrides))
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


class RecordingDestination:
    """A stand-in destination that records what it was asked to do."""

    id = "recorder"
    display_name = "Recorder"
    capabilities = Capabilities(create=True, update=True, close=True)

    def __init__(self):
        self.pushed: list[str] = []
        self.updated: list[str] = []

    def config_schema(self):
        return {}

    def push(self, task):
        self.pushed.append(task.id)
        return ExternalRef(provider=self.id, external_id=f"REC-{len(self.pushed)}")

    def update(self, task, ref):
        self.updated.append(ref.external_id)

    def close(self, task, ref):
        pass


@pytest.fixture
def recorder(monkeypatch):
    """Register a temporary destination and make sure it counts as enabled."""
    from app.core.config import get_settings

    provider = RecordingDestination()
    registry.register_destination(provider)
    monkeypatch.setattr(
        get_settings(), "enabled_destinations", ["local", "jira", "recorder"], raising=False
    )
    try:
        yield provider
    finally:
        registry._destinations.pop("recorder", None)


# -- resolution ----------------------------------------------------------


def test_resolution_falls_back_to_local(db):
    assert resolve_destination(db, make_task(db)) == "local"


def test_project_default_applies_when_the_task_has_none(db, recorder):
    set_route(db, "Platform", "recorder")
    task = make_task(db, project="Platform")

    assert resolve_destination(db, task) == "recorder"


def test_task_destination_beats_the_project_default(db, recorder):
    set_route(db, "Platform", "recorder")
    task = make_task(db, project="Platform", destination="local")

    assert resolve_destination(db, task) == "local"


def test_project_default_can_be_cleared(db, recorder):
    set_route(db, "Platform", "recorder")
    set_route(db, "Platform", None)

    assert resolve_destination(db, make_task(db, project="Platform")) == "local"


def test_setting_a_route_to_an_unknown_destination_is_rejected(db):
    with pytest.raises(RoutingError):
        set_route(db, "Platform", "myspace")


# -- the guardrail -------------------------------------------------------


def test_a_jira_sourced_task_cannot_be_pushed_to_jira_as_new(db):
    """The phase 6 guardrail: no silent duplicate of the issue it came from."""
    task = make_task(db, source_provider="jira", source_ref="OPS-1")

    with pytest.raises(RoutingError, match="would create a duplicate"):
        check_push_allowed(task, "jira")


def test_a_jira_sourced_task_may_still_be_updated_in_jira(db):
    """Updating the original is the whole point — only creating is blocked."""
    task = make_task(
        db, source_provider="jira", source_ref="OPS-1", external_refs={"jira": "OPS-1"}
    )
    check_push_allowed(task, "jira")  # must not raise


def test_the_guardrail_is_not_jira_specific(db):
    """Every adapter that is both source and destination has this trap."""
    task = make_task(db, source_provider="recorder", source_ref="REC-9")

    with pytest.raises(RoutingError):
        check_push_allowed(task, "recorder")


def test_a_csv_sourced_task_pushes_to_jira_freely(db):
    check_push_allowed(make_task(db, source_provider="csv"), "jira")


def test_push_is_blocked_end_to_end_for_a_jira_round_trip(db, recorder):
    task = make_task(db, source_provider="recorder", source_ref="REC-1", destination="recorder")

    with pytest.raises(RoutingError):
        push_task(db, task)
    assert recorder.pushed == []


# -- pushing -------------------------------------------------------------


def test_push_records_the_external_ref(db, recorder):
    task = make_task(db, destination="recorder")
    outcome = push_task(db, task)

    assert outcome.action == "created"
    assert outcome.external_id == "REC-1"
    assert task.external_refs == {"recorder": "REC-1"}


def test_pushing_twice_updates_rather_than_creating_again(db, recorder):
    task = make_task(db, destination="recorder")
    push_task(db, task)
    outcome = push_task(db, task)

    assert outcome.action == "updated"
    assert recorder.pushed == [task.id]  # created once
    assert recorder.updated == ["REC-1"]  # updated once
    assert task.external_refs == {"recorder": "REC-1"}


def test_push_to_local_is_a_no_op_that_still_records(db):
    task = make_task(db)
    outcome = push_task(db, task, "local")

    assert outcome.destination == "local"
    assert task.external_refs == {"local": task.id}


def test_external_refs_survive_a_reload(db, recorder):
    """PortableJSON tracks by identity — reassignment, not mutation."""
    task = make_task(db, destination="recorder")
    push_task(db, task)

    db.expire_all()
    reloaded = db.get(Task, task.id)
    assert reloaded.external_refs == {"recorder": "REC-1"}


def test_pushing_to_an_unknown_destination_is_an_error(db):
    with pytest.raises(RoutingError):
        push_task(db, make_task(db), "myspace")
