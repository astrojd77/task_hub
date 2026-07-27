"""Thin Jira REST v3 client.

Shared by the Jira source (phase 4) and the Jira destination (phase 6) so the
auth, error translation and ADF handling exist once. It knows nothing about
canonical enums — that translation belongs to the adapters.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.providers.base import ProviderError, ProviderNotConfigured

#: Fields we ask Jira for. Requesting explicitly keeps responses small and
#: makes it obvious what the adapters are allowed to depend on.
BASE_FIELDS = (
    "summary",
    "description",
    "status",
    "priority",
    "duedate",
    "assignee",
    "project",
    "labels",
    "issuetype",
)


class JiraClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _require_config(self) -> None:
        if not self.settings.jira_configured:
            raise ProviderNotConfigured(
                "Jira is not configured — set JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN"
            )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        self._require_config()
        url = f"{self.settings.jira_base_url.rstrip('/')}{path}"
        try:
            response = httpx.request(
                method,
                url,
                auth=(self.settings.jira_email, self.settings.jira_api_token),
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=self.settings.jira_timeout_seconds,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"could not reach Jira: {exc}") from exc

        if response.status_code == 401:
            raise ProviderError("Jira rejected the credentials (401)")
        if response.status_code == 403:
            raise ProviderError("Jira denied access (403) — check the account's permissions")
        if response.status_code == 404:
            raise ProviderError("Jira returned 404 — check the issue key or the base URL")
        if response.status_code >= 400:
            raise ProviderError(f"Jira error {response.status_code}: {_first_error(response)}")

        if not response.content:
            return {}
        try:
            # Most endpoints return an object; /field returns a bare array.
            return response.json()
        except ValueError as exc:
            raise ProviderError("Jira returned a response that was not JSON") from exc

    # -- reads -----------------------------------------------------------

    def get_issue(self, key: str, extra_fields: tuple[str, ...] = ()) -> dict:
        fields = ",".join((*BASE_FIELDS, *extra_fields))
        return self._request("GET", f"/rest/api/3/issue/{key}", params={"fields": fields})

    def search(self, jql: str, extra_fields: tuple[str, ...] = (), limit: int = 100) -> list[dict]:
        payload = {
            "jql": jql,
            "maxResults": min(limit, self.settings.jira_max_results),
            "fields": [*BASE_FIELDS, *extra_fields],
        }
        body = self._request("POST", "/rest/api/3/search/jql", json=payload)
        return body.get("issues", [])

    def list_fields(self) -> list[dict]:
        """Every field this instance has, stock and custom.

        Backs the mapping screen's dropdown, so nobody has to remember that
        Severity is customfield_10042.
        """
        body = self._request("GET", "/rest/api/3/field")
        return body if isinstance(body, list) else []

    # -- writes ----------------------------------------------------------

    def create_issue(self, fields: dict) -> dict:
        return self._request("POST", "/rest/api/3/issue", json={"fields": fields})

    def update_issue(self, key: str, fields: dict) -> None:
        self._request("PUT", f"/rest/api/3/issue/{key}", json={"fields": fields})

    def transitions(self, key: str) -> list[dict]:
        return self._request("GET", f"/rest/api/3/issue/{key}/transitions").get("transitions", [])

    def transition(self, key: str, transition_id: str) -> None:
        self._request(
            "POST",
            f"/rest/api/3/issue/{key}/transitions",
            json={"transition": {"id": transition_id}},
        )

    def browse_url(self, key: str) -> str:
        return f"{self.settings.jira_base_url.rstrip('/')}/browse/{key}"


def _first_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    messages = body.get("errorMessages") or []
    if messages:
        return str(messages[0])
    errors = body.get("errors") or {}
    if errors:
        return "; ".join(f"{k}: {v}" for k, v in errors.items())
    return response.text[:200]


def adf_to_text(value: Any) -> str | None:
    """Flatten Atlassian Document Format into plain text.

    Jira's v3 API returns rich descriptions as a nested ADF document. We only
    want readable text for the review screen; the original stays in
    ``raw_payload`` for anyone who needs the structure back.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None

    chunks: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            node_type = node.get("type")
            if node_type == "text":
                chunks.append(node.get("text", ""))
            elif node_type == "hardBreak":
                chunks.append("\n")
            for child in node.get("content", []) or []:
                walk(child)
            if node_type in {"paragraph", "heading", "listItem", "blockquote"}:
                chunks.append("\n")
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    text = "".join(chunks).strip()
    return text or None


def text_to_adf(text: str | None) -> dict:
    """Wrap plain text as a minimal ADF document for writes."""
    paragraphs = (text or "").split("\n")
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": ([{"type": "text", "text": line}] if line else []),
            }
            for line in paragraphs
        ],
    }
