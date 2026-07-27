"""Jira source — targeted fetch only.

Either **one issue key** or **one JQL query**. There is deliberately no
"import everything" path: this is an import-and-manage hub, not a mirror of
Jira.

Like every adapter, this module owns the translation between Jira's vocabulary
and the canonical enums. Jira status categories and priority names never leak
past this file.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.config import get_settings
from app.core.enums import Criticality, ImpactSize, Priority, TaskStatus
from app.core.parsing import parse_date
from app.providers.base import ProviderError, RawItem
from app.providers.jira_client import JiraClient, adf_to_text
from app.providers.registry import source
from app.schemas.task import DraftTask

ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")

#: Jira's own status *categories* are the stable signal; individual workflow
#: status names vary per project and are matched first where we recognise them.
_STATUS_NAMES: dict[str, TaskStatus] = {
    "to do": TaskStatus.TODO,
    "todo": TaskStatus.TODO,
    "open": TaskStatus.TODO,
    "backlog": TaskStatus.TODO,
    "selected for development": TaskStatus.TODO,
    "in progress": TaskStatus.IN_PROGRESS,
    "in review": TaskStatus.IN_PROGRESS,
    "in development": TaskStatus.IN_PROGRESS,
    "blocked": TaskStatus.BLOCKED,
    "on hold": TaskStatus.BLOCKED,
    "waiting": TaskStatus.BLOCKED,
    "waiting for support": TaskStatus.BLOCKED,
    "impeded": TaskStatus.BLOCKED,
    "done": TaskStatus.DONE,
    "closed": TaskStatus.DONE,
    "resolved": TaskStatus.DONE,
    "complete": TaskStatus.DONE,
}

_STATUS_CATEGORIES: dict[str, TaskStatus] = {
    "new": TaskStatus.TODO,
    "indeterminate": TaskStatus.IN_PROGRESS,
    "done": TaskStatus.DONE,
}

_PRIORITY_NAMES: dict[str, Priority] = {
    "lowest": Priority.LOW,
    "low": Priority.LOW,
    "minor": Priority.LOW,
    "trivial": Priority.LOW,
    "p4": Priority.LOW,
    "p3": Priority.LOW,
    "medium": Priority.MEDIUM,
    "normal": Priority.MEDIUM,
    "p2": Priority.MEDIUM,
    "high": Priority.HIGH,
    "major": Priority.HIGH,
    "p1": Priority.HIGH,
    "highest": Priority.URGENT,
    "critical": Priority.URGENT,
    "blocker": Priority.URGENT,
    "p0": Priority.URGENT,
}

_CRITICALITY_NAMES: dict[str, Criticality] = {
    "low": Criticality.LOW,
    "minor": Criticality.LOW,
    "sev4": Criticality.LOW,
    "sev 4": Criticality.LOW,
    "medium": Criticality.MEDIUM,
    "moderate": Criticality.MEDIUM,
    "sev3": Criticality.MEDIUM,
    "sev 3": Criticality.MEDIUM,
    "high": Criticality.HIGH,
    "major": Criticality.HIGH,
    "sev2": Criticality.HIGH,
    "sev 2": Criticality.HIGH,
    "critical": Criticality.CRITICAL,
    "severe": Criticality.CRITICAL,
    "sev1": Criticality.CRITICAL,
    "sev 1": Criticality.CRITICAL,
}

_IMPACT_NAMES: dict[str, ImpactSize] = {
    "xs": ImpactSize.XS,
    "extra small": ImpactSize.XS,
    "s": ImpactSize.S,
    "small": ImpactSize.S,
    "m": ImpactSize.M,
    "medium": ImpactSize.M,
    "l": ImpactSize.L,
    "large": ImpactSize.L,
    "xl": ImpactSize.XL,
    "extra large": ImpactSize.XL,
    "massive": ImpactSize.XL,
}


def map_status(status: dict | None) -> tuple[TaskStatus, str | None]:
    """Workflow name first, then Jira's status category as the fallback."""
    if not status:
        return TaskStatus.TODO, "no status on the issue — defaulted to todo"

    name = (status.get("name") or "").strip().lower()
    if name in _STATUS_NAMES:
        return _STATUS_NAMES[name], None

    category = ((status.get("statusCategory") or {}).get("key") or "").strip().lower()
    if category in _STATUS_CATEGORIES:
        mapped = _STATUS_CATEGORIES[category]
        return mapped, (
            f"status {status.get('name')!r} is not one we know; used its Jira category "
            f"({category}) and got {mapped.value}"
        )

    return TaskStatus.TODO, f"status {status.get('name')!r} did not map — defaulted to todo"


def map_priority(priority: dict | None) -> tuple[Priority, str | None]:
    if not priority:
        return Priority.MEDIUM, None
    name = (priority.get("name") or "").strip().lower()
    if name in _PRIORITY_NAMES:
        return _PRIORITY_NAMES[name], None
    return Priority.MEDIUM, f"priority {priority.get('name')!r} did not map — defaulted to medium"


def _custom_value(raw: Any) -> str | None:
    """Custom fields come back as a string, a {value: ...} option, or a list."""
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw.strip() or None
    if isinstance(raw, dict):
        for key in ("value", "name"):
            if raw.get(key):
                return str(raw[key]).strip()
        return None
    if isinstance(raw, list) and raw:
        return _custom_value(raw[0])
    if isinstance(raw, (int, float)):
        return str(raw)
    return None


@source
class JiraSource:
    id = "jira"
    display_name = "Jira"

    def __init__(self, client: JiraClient | None = None) -> None:
        # Injectable so tests never touch the network.
        self._client = client

    @property
    def client(self) -> JiraClient:
        return self._client or JiraClient()

    def config_schema(self) -> dict[str, Any]:
        settings = get_settings()
        return {
            "type": "object",
            "description": "Provide exactly one of issue_key or jql.",
            "properties": {
                "issue_key": {"type": "string", "example": "OPS-123"},
                "jql": {
                    "type": "string",
                    "example": "project = OPS AND status != Done ORDER BY duedate",
                },
                "limit": {"type": "integer", "default": settings.jira_max_results},
            },
            "configured": settings.jira_configured,
            "criticality_field": settings.jira_criticality_field or None,
            "impact_field": settings.jira_impact_field or None,
        }

    def _extra_fields(self) -> tuple[str, ...]:
        settings = get_settings()
        return tuple(f for f in (settings.jira_criticality_field, settings.jira_impact_field) if f)

    def describe(self, config: dict[str, Any]) -> dict[str, Any]:
        settings = get_settings()
        key = (config.get("issue_key") or "").strip()
        return {
            "target": f"issue {key}" if key else f"JQL: {(config.get('jql') or '').strip()}",
            "criticality_field": settings.jira_criticality_field or None,
            "impact_field": settings.jira_impact_field or None,
            # A single issue gets a modal; a query gets the review table.
            "review_style": "modal" if key else "table",
        }

    def fetch(self, config: dict[str, Any]) -> list[RawItem]:
        key = (config.get("issue_key") or "").strip()
        jql = (config.get("jql") or "").strip()

        if key and jql:
            raise ProviderError("give either an issue key or a JQL query, not both")
        if not key and not jql:
            raise ProviderError("give an issue key or a JQL query")

        extra = self._extra_fields()

        if key:
            if not ISSUE_KEY.match(key.upper()):
                raise ProviderError(f"{key!r} does not look like a Jira issue key (e.g. OPS-123)")
            issues = [self.client.get_issue(key.upper(), extra)]
        else:
            limit = int(config.get("limit") or get_settings().jira_max_results)
            issues = self.client.search(jql, extra, limit=limit)

        return [
            RawItem(source_ref=issue["key"], payload=issue) for issue in issues if issue.get("key")
        ]

    def to_draft(self, raw: RawItem) -> DraftTask:
        settings = get_settings()
        issue = raw.payload
        fields = issue.get("fields") or {}
        warnings: list[str] = []

        status, status_warning = map_status(fields.get("status"))
        if status_warning:
            warnings.append(status_warning)

        priority, priority_warning = map_priority(fields.get("priority"))
        if priority_warning:
            warnings.append(priority_warning)

        due_date, date_warning = parse_date(fields.get("duedate"))
        if date_warning:
            warnings.append(date_warning)

        criticality = self._mapped_enum(
            fields, settings.jira_criticality_field, _CRITICALITY_NAMES, "criticality", warnings
        )
        impact = self._mapped_enum(
            fields, settings.jira_impact_field, _IMPACT_NAMES, "impact", warnings
        )

        assignee = (fields.get("assignee") or {}).get("displayName")
        project = (fields.get("project") or {}).get("name") or (fields.get("project") or {}).get(
            "key"
        )

        return DraftTask(
            title=(fields.get("summary") or "").strip(),
            description=adf_to_text(fields.get("description")),
            status=status,
            priority=priority,
            criticality=criticality,
            impact_size=impact,
            due_date=due_date,
            assignee=assignee,
            project=project,
            labels=list(fields.get("labels") or []),
            source_provider=self.id,
            source_ref=issue["key"],
            raw_payload=issue,
            warnings=warnings,
        )

    def _mapped_enum(
        self,
        fields: dict,
        field_id: str,
        table: dict,
        label: str,
        warnings: list[str],
    ):
        """Read a configured custom field, or leave it for the review popup.

        Three distinct outcomes, and the user is told which one happened:
        no field configured (silent — this is the normal case), field
        configured but empty on the issue, or a value that is off our scale.
        """
        if not field_id:
            return None

        value = _custom_value(fields.get(field_id))
        if value is None:
            warnings.append(f"{label} field {field_id} is empty on this issue — set it below")
            return None

        mapped = table.get(value.strip().lower())
        if mapped is None:
            warnings.append(f"{label} {value!r} from {field_id} is not on the scale — set it below")
        return mapped
