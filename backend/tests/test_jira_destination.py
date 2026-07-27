"""Jira destination: canonical enums translated back out. No network."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.core.config import get_settings
from app.providers.base import ExternalRef, ProviderNotConfigured
from app.providers.destinations.jira import JiraDestination
from app.providers.jira_client import adf_to_text
from app.schemas.task import TaskOut


class FakeClient:
    def __init__(self, transitions=None):
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []
        self.transitioned: list[tuple[str, str]] = []
        self._transitions = (
            transitions
            if transitions is not None
            else [
                {"id": "11", "name": "In Progress", "to": {"name": "In Progress"}},
                {"id": "21", "name": "Done", "to": {"name": "Done"}},
            ]
        )

    def create_issue(self, fields):
        self.created.append(fields)
        return {"key": "OPS-99"}

    def update_issue(self, key, fields):
        self.updated.append((key, fields))

    def transitions(self, key):
        return self._transitions

    def transition(self, key, transition_id):
        self.transitioned.append((key, transition_id))

    def browse_url(self, key):
        return f"https://jira.example.com/browse/{key}"


def task(**overrides) -> TaskOut:
    base = {
        "id": "abc-123",
        "summary": "Rotate signing cert",
        "description": "Expires soon",
        "status": "todo",
        "priority": "high",
        "criticality": None,
        "impact_size": None,
        "due_date": None,
        "assignee": None,
        "project": None,
        "labels": [],
        "custom_fields": {},
        "source_provider": "csv",
        "source_ref": "row-1",
        "external_refs": {},
        "destination": "jira",
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
    }
    return TaskOut(**(base | overrides))


@pytest.fixture(autouse=True)
def jira_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "jira_base_url", "https://jira.example.com", raising=False)
    monkeypatch.setattr(settings, "jira_email", "me@example.com", raising=False)
    monkeypatch.setattr(settings, "jira_api_token", "token", raising=False)
    monkeypatch.setattr(settings, "jira_project_key", "OPS", raising=False)
    monkeypatch.setattr(settings, "jira_issue_type", "Task", raising=False)
    monkeypatch.setattr(settings, "jira_criticality_field", "", raising=False)
    monkeypatch.setattr(settings, "jira_impact_field", "", raising=False)
    return settings


def dest(transitions=None) -> JiraDestination:
    return JiraDestination(client=FakeClient(transitions))


# -- create --------------------------------------------------------------


def test_push_creates_an_issue_and_returns_its_key():
    d = dest()
    ref = d.push(task())

    assert ref.external_id == "OPS-99"
    assert ref.url == "https://jira.example.com/browse/OPS-99"
    assert d.client.created[0]["project"] == {"key": "OPS"}
    assert d.client.created[0]["issuetype"] == {"name": "Task"}
    assert d.client.created[0]["summary"] == "Rotate signing cert"


def test_priority_translates_to_jiras_scale():
    d = dest()
    d.push(task(priority="urgent"))
    assert d.client.created[0]["priority"] == {"name": "Highest"}


def test_description_goes_out_as_adf():
    d = dest()
    d.push(task(description="Line one\nLine two"))
    assert adf_to_text(d.client.created[0]["description"]) == "Line one\nLine two"


def test_due_date_is_sent_as_an_iso_date():
    d = dest()
    d.push(task(due_date=date(2026, 8, 1)))
    assert d.client.created[0]["duedate"] == "2026-08-01"


def test_missing_project_key_is_a_clear_configuration_error(monkeypatch):
    monkeypatch.setattr(get_settings(), "jira_project_key", "", raising=False)
    with pytest.raises(ProviderNotConfigured, match="JIRA_PROJECT_KEY"):
        dest().push(task())


# -- criticality and impact ----------------------------------------------


def test_criticality_and_impact_become_labels_when_no_field_is_configured():
    """Jira has no such concept by default — don't just drop the information."""
    d = dest()
    d.push(task(criticality="critical", impact_size="xl", labels=["security"]))

    labels = d.client.created[0]["labels"]
    assert "security" in labels
    assert "taskhub-crit-critical" in labels
    assert "taskhub-impact-xl" in labels


def test_configured_custom_fields_are_used_instead_of_labels(monkeypatch):
    monkeypatch.setattr(get_settings(), "jira_criticality_field", "customfield_1", raising=False)
    monkeypatch.setattr(get_settings(), "jira_impact_field", "customfield_2", raising=False)

    d = dest()
    d.push(task(criticality="high", impact_size="l"))
    fields = d.client.created[0]

    assert fields["customfield_1"] == {"value": "High"}
    assert fields["customfield_2"] == {"value": "L"}
    assert "labels" not in fields


def test_labels_with_spaces_are_hyphenated():
    """Jira rejects labels containing spaces."""
    d = dest()
    d.push(task(labels=["needs review"]))
    assert d.client.created[0]["labels"] == ["needs-review"]


# -- status transitions --------------------------------------------------


def test_a_todo_task_needs_no_transition_on_create():
    d = dest()
    d.push(task(status="todo"))
    assert d.client.transitioned == []


def test_status_is_applied_as_a_transition_after_create():
    d = dest()
    d.push(task(status="in_progress"))
    assert d.client.transitioned == [("OPS-99", "11")]


def test_transition_matches_on_the_target_status_name_too():
    d = dest([{"id": "31", "name": "Ship it", "to": {"name": "Done"}}])
    d.update(task(status="done"), ExternalRef(provider="jira", external_id="OPS-5"))
    assert d.client.transitioned == [("OPS-5", "31")]


def test_a_workflow_without_a_matching_transition_is_left_alone():
    """Better than failing the whole push because a workflow lacks 'Blocked'."""
    d = dest([{"id": "11", "name": "In Progress", "to": {"name": "In Progress"}}])
    d.push(task(status="blocked"))

    assert d.client.transitioned == []
    assert d.client.created  # the issue was still created


# -- update and close ----------------------------------------------------


def test_update_does_not_resend_project_or_issue_type():
    """Those are immutable on an existing issue."""
    d = dest()
    d.update(task(status="done"), ExternalRef(provider="jira", external_id="OPS-5"))

    key, fields = d.client.updated[0]
    assert key == "OPS-5"
    assert "project" not in fields
    assert "issuetype" not in fields
    assert fields["summary"] == "Rotate signing cert"


def test_close_transitions_to_done():
    d = dest()
    d.close(task(status="in_progress"), ExternalRef(provider="jira", external_id="OPS-5"))
    assert d.client.transitioned == [("OPS-5", "21")]


def test_capabilities_are_declared():
    from app.providers.registry import registry

    caps = registry.destination("jira").capabilities
    assert (caps.create, caps.update, caps.close) == (True, True, True)
