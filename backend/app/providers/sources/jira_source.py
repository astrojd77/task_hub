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
from app.providers.jira_client import BASE_FIELDS, JiraClient, adf_to_text
from app.providers.registry import source
from app.schemas.task import DraftTask
from app.services.source_mapping import EMPTY_MAPPING, mapping_from_config, translate_enum

ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")

#: Canonical field -> the Jira field that feeds it out of the box. Every one of
#: these is remappable, which is what lets an instance whose "real" due date
#: lives in a custom field work without a code change.
DEFAULT_INPUTS: dict[str, str] = {
    "summary": "summary",
    "description": "description",
    "status": "status",
    "priority": "priority",
    "due_date": "duedate",
    "assignee": "assignee",
    "project": "project",
    "labels": "labels",
}

#: Offered by the mapping screen alongside whatever custom fields exist.
BASE_INPUT_LABELS: dict[str, str] = {
    "summary": "Summary",
    "description": "Description",
    "status": "Status",
    "priority": "Priority",
    "duedate": "Due date",
    "assignee": "Assignee",
    "project": "Project",
    "labels": "Labels",
    "issuetype": "Issue type",
}

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


def map_status(status: dict | None, mapping: Any = EMPTY_MAPPING) -> tuple[TaskStatus, str | None]:
    """Configured rules, then workflow name, then Jira's status category.

    The category fallback matters because workflow status names are per-project
    and unknowable in advance, whereas the category always exists.
    """
    if not status:
        return TaskStatus.TODO, "no status on the issue — defaulted to todo"

    raw_name = (status.get("name") or "").strip()
    configured, matched = mapping.translate("status", raw_name)
    if matched:
        return configured, None

    name = raw_name.lower()
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


def map_priority(
    priority: dict | None, mapping: Any = EMPTY_MAPPING
) -> tuple[Priority, str | None]:
    if not priority:
        return Priority.MEDIUM, None

    raw_name = (priority.get("name") or "").strip()
    configured, matched = mapping.translate("priority", raw_name)
    if matched:
        return configured, None

    if raw_name.lower() in _PRIORITY_NAMES:
        return _PRIORITY_NAMES[raw_name.lower()], None
    return Priority.MEDIUM, f"priority {raw_name!r} did not map — defaulted to medium"


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

    def _extra_fields(self, config: dict[str, Any] | None = None) -> tuple[str, ...]:
        """Non-standard Jira fields this fetch needs to ask for.

        Anything a mapping points at that is not one of Jira's stock fields has
        to be named explicitly in the request, or Jira simply will not return
        it. The env-var settings remain as a fallback for instances configured
        before the mapping screen existed.
        """
        settings = get_settings()
        mapping = mapping_from_config(config or {})

        wanted = {settings.jira_criticality_field, settings.jira_impact_field}
        for field_mapping in mapping.fields.values():
            if field_mapping.source_expr:
                wanted.add(field_mapping.source_expr)

        return tuple(sorted(f for f in wanted if f and f not in BASE_FIELDS))

    def mappable_inputs(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Jira's stock fields, plus this instance's custom fields.

        Discovering the custom fields is what turns "type customfield_10042 from
        memory" into picking "Severity" from a list. It needs a live connection,
        so a failure degrades to the stock list rather than breaking the screen.
        """
        inputs = [{"key": k, "label": v} for k, v in BASE_INPUT_LABELS.items()]

        if not get_settings().jira_configured:
            return inputs

        try:
            for field in self.client.list_fields():
                if field.get("custom") and field.get("id"):
                    inputs.append(
                        {
                            "key": field["id"],
                            "label": field.get("name") or field["id"],
                            "hint": "custom field",
                        }
                    )
        except ProviderError:
            # Unreachable or unauthorised — the stock list still lets the user
            # map by hand.
            pass

        return inputs

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

        extra = self._extra_fields(config)

        if key:
            if not ISSUE_KEY.match(key.upper()):
                raise ProviderError(f"{key!r} does not look like a Jira issue key (e.g. OPS-123)")
            issues = [self.client.get_issue(key.upper(), extra)]
        else:
            limit = int(config.get("limit") or get_settings().jira_max_results)
            issues = self.client.search(jql, extra, limit=limit)

        # The resolver rides along on each item so to_draft can apply the
        # mapping without needing the config or a database session.
        mapping = mapping_from_config(config)
        return [
            RawItem(source_ref=issue["key"], payload={**issue, "_mapping": mapping})
            for issue in issues
            if issue.get("key")
        ]

    def to_draft(self, raw: RawItem) -> DraftTask:
        settings = get_settings()
        issue = raw.payload
        fields = issue.get("fields") or {}
        mapping = raw.payload.get("_mapping") or EMPTY_MAPPING
        warnings: list[str] = []

        def source_field(field_key: str):
            """Read whichever Jira field is mapped to this canonical field."""
            return fields.get(mapping.input_for(field_key, DEFAULT_INPUTS.get(field_key)))

        status, status_warning = map_status(source_field("status"), mapping)
        if status_warning:
            warnings.append(status_warning)

        priority, priority_warning = map_priority(source_field("priority"), mapping)
        if priority_warning:
            warnings.append(priority_warning)

        due_date, date_warning = parse_date(source_field("due_date"))
        if date_warning:
            warnings.append(date_warning)

        criticality = self._mapped_enum(
            fields,
            mapping.input_for("criticality", settings.jira_criticality_field),
            _CRITICALITY_NAMES,
            "criticality",
            mapping,
            "criticality",
            warnings,
        )
        impact = self._mapped_enum(
            fields,
            mapping.input_for("impact_size", settings.jira_impact_field),
            _IMPACT_NAMES,
            "impact",
            mapping,
            "impact_size",
            warnings,
        )

        assignee = (source_field("assignee") or {}).get("displayName")
        raw_project = source_field("project") or {}
        project = raw_project.get("name") or raw_project.get("key")

        return DraftTask(
            summary=(source_field("summary") or "").strip(),
            description=adf_to_text(source_field("description")),
            status=status,
            priority=priority,
            criticality=criticality,
            impact_size=impact,
            due_date=due_date,
            assignee=assignee,
            project=project,
            labels=list(source_field("labels") or []),
            source_provider=self.id,
            source_ref=issue["key"],
            custom_fields=self._custom_fields(fields, mapping),
            raw_payload={k: v for k, v in issue.items() if k != "_mapping"},
            warnings=warnings,
        )

    @staticmethod
    def _custom_fields(fields: dict, mapping) -> dict[str, str]:
        """Configured custom fields, read from whichever Jira field feeds them.

        The adapter needs no knowledge of what Type or Platform mean — only
        that a mapping points at a Jira field, and that the field is not one of
        the canonical ones.
        """
        values: dict[str, str] = {}
        for field_key, field_mapping in mapping.fields.items():
            if field_key in DEFAULT_INPUTS or field_key in {"criticality", "impact_size"}:
                continue
            if not field_mapping.source_expr:
                continue
            native = _custom_value(fields.get(field_mapping.source_expr))
            if native is None:
                continue
            translated, matched = mapping.translate(field_key, native)
            values[field_key] = translated if matched else native
        return values

    def _mapped_enum(
        self,
        fields: dict,
        field_id: str,
        table: dict,
        label: str,
        mapping,
        field_key: str,
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

        return translate_enum(mapping, field_key, value, table, label, warnings)
