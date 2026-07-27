"""Jira destination — push a committed task out as an issue.

The reverse of ``sources/jira_source.py``: canonical enums translate *out* into
Jira's vocabulary here, and nothing outside this file knows what a Jira
transition is.
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.enums import Criticality, ImpactSize, Priority, TaskStatus
from app.providers.base import Capabilities, ExternalRef, ProviderError, ProviderNotConfigured
from app.providers.jira_client import JiraClient, text_to_adf
from app.providers.registry import destination
from app.schemas.task import TaskOut

#: Canonical priority -> Jira's default priority scheme.
_PRIORITY_OUT: dict[str, str] = {
    Priority.LOW: "Low",
    Priority.MEDIUM: "Medium",
    Priority.HIGH: "High",
    Priority.URGENT: "Highest",
}

#: Canonical status -> the transition names we will look for, in order.
_STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    TaskStatus.TODO: ("To Do", "Open", "Backlog", "Reopen"),
    TaskStatus.IN_PROGRESS: ("In Progress", "Start Progress", "In Development"),
    TaskStatus.BLOCKED: ("Blocked", "On Hold", "Impeded"),
    TaskStatus.DONE: ("Done", "Close", "Closed", "Resolve", "Resolved", "Complete"),
}

#: Criticality / impact go out as labels when no custom field is configured.
#: Labels are the one field every Jira project has, so the information is not
#: simply lost — but it is clearly marked as ours.
_CRITICALITY_LABEL = {
    Criticality.LOW: "taskhub-crit-low",
    Criticality.MEDIUM: "taskhub-crit-medium",
    Criticality.HIGH: "taskhub-crit-high",
    Criticality.CRITICAL: "taskhub-crit-critical",
}
_IMPACT_LABEL = {
    ImpactSize.XS: "taskhub-impact-xs",
    ImpactSize.S: "taskhub-impact-s",
    ImpactSize.M: "taskhub-impact-m",
    ImpactSize.L: "taskhub-impact-l",
    ImpactSize.XL: "taskhub-impact-xl",
}


@destination
class JiraDestination:
    id = "jira"
    display_name = "Jira"
    capabilities = Capabilities(create=True, update=True, close=True)

    def __init__(self, client: JiraClient | None = None) -> None:
        self._client = client

    @property
    def client(self) -> JiraClient:
        return self._client or JiraClient()

    def config_schema(self) -> dict[str, Any]:
        settings = get_settings()
        return {
            "type": "object",
            "properties": {},
            "configured": bool(settings.jira_configured and settings.jira_project_key),
            "project_key": settings.jira_project_key or None,
            "issue_type": settings.jira_issue_type,
            "criticality_field": settings.jira_criticality_field or None,
            "impact_field": settings.jira_impact_field or None,
        }

    # -- field mapping ---------------------------------------------------

    def _fields_for(self, task: TaskOut, *, include_project: bool) -> dict:
        settings = get_settings()
        fields: dict[str, Any] = {
            "summary": task.summary[:255],
            "description": text_to_adf(task.description),
        }

        if include_project:
            if not settings.jira_project_key:
                raise ProviderNotConfigured(
                    "set JIRA_PROJECT_KEY before pushing new issues to Jira"
                )
            fields["project"] = {"key": settings.jira_project_key}
            fields["issuetype"] = {"name": settings.jira_issue_type}

        if task.priority in _PRIORITY_OUT:
            fields["priority"] = {"name": _PRIORITY_OUT[task.priority]}

        if task.due_date:
            fields["duedate"] = task.due_date.isoformat()

        # Criticality and impact go to their configured custom fields if we have
        # them, and to labels otherwise, so the information survives either way.
        labels = list(task.labels)
        if task.criticality:
            if settings.jira_criticality_field:
                fields[settings.jira_criticality_field] = {"value": task.criticality.capitalize()}
            else:
                labels.append(_CRITICALITY_LABEL[task.criticality])
        if task.impact_size:
            if settings.jira_impact_field:
                fields[settings.jira_impact_field] = {"value": task.impact_size.upper()}
            else:
                labels.append(_IMPACT_LABEL[task.impact_size])

        if labels:
            # Jira rejects labels containing spaces.
            fields["labels"] = [label.replace(" ", "-") for label in dict.fromkeys(labels)]

        return fields

    # -- operations ------------------------------------------------------

    def push(self, task: TaskOut) -> ExternalRef:
        created = self.client.create_issue(self._fields_for(task, include_project=True))
        key = created.get("key")
        if not key:
            raise ProviderError("Jira accepted the issue but returned no key")

        # Status is a workflow transition, not a field, so it cannot be part of
        # the create call.
        if task.status != TaskStatus.TODO:
            self._transition_to(key, task.status)

        return ExternalRef(provider=self.id, external_id=key, url=self.client.browse_url(key))

    def update(self, task: TaskOut, ref: ExternalRef) -> None:
        self.client.update_issue(ref.external_id, self._fields_for(task, include_project=False))
        self._transition_to(ref.external_id, task.status)

    def close(self, task: TaskOut, ref: ExternalRef) -> None:
        self._transition_to(ref.external_id, TaskStatus.DONE)

    def _transition_to(self, key: str, status: str) -> None:
        """Move an issue to the workflow state matching a canonical status.

        Jira workflows are per-project and we cannot know their transition
        names in advance, so this matches against what the issue actually
        offers right now and quietly does nothing when there is no match —
        failing a whole push because a workflow lacks a "Blocked" step would be
        worse than leaving the status alone.
        """
        wanted = _STATUS_TRANSITIONS.get(status)
        if not wanted:
            return

        available = self.client.transitions(key)
        by_name = {(t.get("name") or "").strip().lower(): t for t in available}
        # Also match on the transition's *target* status, which is often named
        # more consistently than the transition itself.
        by_target = {((t.get("to") or {}).get("name") or "").strip().lower(): t for t in available}

        for candidate in wanted:
            match = by_name.get(candidate.lower()) or by_target.get(candidate.lower())
            if match and match.get("id"):
                self.client.transition(key, match["id"])
                return
