"""Provider interfaces.

Two protocols, and core depends on nothing else. The test of this abstraction:
adding a destination must not require touching the calendar, the task list, the
watch view, or the normalizer. If it does, the abstraction is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.schemas.task import DraftTask, TaskOut


@dataclass(frozen=True)
class UploadedFile:
    """A file handed to a file-based source (CSV, email).

    The API layer puts this under ``config["file"]`` so that
    ``SourceProvider.fetch(config)`` stays a single uniform entry point whether
    a source needs an upload (csv, email) or only credentials (jira).
    """

    filename: str
    content: bytes


@dataclass(frozen=True)
class RawItem:
    """One unit of work as the source handed it over, before normalisation."""

    #: Stable idempotency key *within* this source: csv row hash, Jira issue
    #: key, email Message-ID.
    source_ref: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalRef:
    """Where a committed task ended up on a destination platform."""

    provider: str
    external_id: str
    url: str | None = None


@dataclass(frozen=True)
class Capabilities:
    create: bool = False
    update: bool = False
    close: bool = False

    def as_dict(self) -> dict[str, bool]:
        return {"create": self.create, "update": self.update, "close": self.close}


@runtime_checkable
class SourceProvider(Protocol):
    """Produces drafts. Must never write to the database.

    Every path into the task store goes through review + ``/api/commit``.
    """

    id: str
    display_name: str

    def config_schema(self) -> dict[str, Any]:
        """JSON-schema-ish description of what this source needs to run."""
        ...

    def fetch(self, config: dict[str, Any]) -> list[RawItem]:
        """Pull raw items. Targeted only — no blanket pulls."""
        ...

    def to_draft(self, raw: RawItem) -> DraftTask:
        """Normalise one raw item into a canonical draft. Sets ``source_ref``."""
        ...

    # Optional extension point, probed with getattr — a source that needs to
    # tell the review UI something about the batch as a whole (CSV: which
    # columns it found and how it mapped them; Jira: the query it ran) may
    # implement:
    #
    #     def describe(self, config: dict) -> dict: ...
    #
    # Whatever it returns lands in ``DraftBatch.meta``. Sources that have
    # nothing to add simply omit the method; the route does not care.


@runtime_checkable
class DestinationProvider(Protocol):
    """Receives committed tasks."""

    id: str
    display_name: str
    capabilities: Capabilities

    def config_schema(self) -> dict[str, Any]: ...

    def push(self, task: TaskOut) -> ExternalRef: ...

    def update(self, task: TaskOut, ref: ExternalRef) -> None: ...

    def close(self, task: TaskOut, ref: ExternalRef) -> None: ...


class ProviderError(RuntimeError):
    """Adapter-level failure that should surface to the user verbatim."""


class ProviderNotConfigured(ProviderError):
    """Adapter is registered but missing credentials/config."""
