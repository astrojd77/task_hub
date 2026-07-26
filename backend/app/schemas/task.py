"""Draft / Task schemas.

The pipeline is deliberately three-legged:

    Source.fetch() -> DraftTask[]     permissive; nothing is persisted
           review UI (modal or table) user edits and selects
    POST /api/commit -> TaskCommitIn  strict; server re-validates everything
                     -> Task rows     idempotent upsert

``DraftTask`` is intentionally lax — an email with no subject or a CSV row with
a junk priority must still survive parsing so it can be *shown* to the user and
fixed. ``TaskCommitIn`` is where the rules bite. The UI is never the only gate.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import Criticality, ImpactSize, Priority, TaskStatus


class DraftTask(BaseModel):
    """An unvalidated, uncommitted candidate task produced by a source."""

    # validate_assignment matters here: drafts are *mutated* after construction
    # (see services/drafts.enrich_with_existing, which copies plain strings off
    # an ORM row). Without it those assignments would slip past the enum types
    # and only surface as a serialisation warning.
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    title: str = ""
    description: str | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: Priority = Priority.MEDIUM
    # Sources almost never supply these two — they are precisely what the
    # review popup exists to capture.
    criticality: Criticality | None = None
    impact_size: ImpactSize | None = None
    due_date: date | None = None
    assignee: str | None = None
    project: str | None = None
    labels: list[str] = Field(default_factory=list)

    source_provider: str
    source_ref: str
    raw_payload: dict | None = None

    #: Non-fatal notes from the adapter, surfaced next to the row in review.
    warnings: list[str] = Field(default_factory=list)
    #: Set when this draft matches a task that was already committed, so the
    #: review UI can show "you have seen this before" instead of implying it is
    #: new. Ignored on commit — the upsert keys off source_provider/source_ref.
    existing_task_id: str | None = None


class TaskCommitIn(DraftTask):
    """A draft the user has reviewed and is asking the server to persist."""

    title: str = Field(min_length=1, max_length=500)
    destination: str | None = None

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v

    @field_validator("source_provider", "source_ref")
    @classmethod
    def _ref_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class CommitRequest(BaseModel):
    drafts: list[TaskCommitIn]
    #: Applied to any draft that does not name its own destination.
    default_destination: str | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None
    status: TaskStatus
    priority: Priority
    criticality: Criticality | None
    impact_size: ImpactSize | None
    due_date: date | None
    assignee: str | None
    project: str | None
    labels: list[str]
    source_provider: str
    source_ref: str
    external_refs: dict
    destination: str | None
    created_at: datetime
    updated_at: datetime


class CommitError(BaseModel):
    index: int
    source_ref: str | None = None
    message: str


class CommitWarning(BaseModel):
    index: int
    source_ref: str | None = None
    message: str


class CommitResult(BaseModel):
    created: int = 0
    updated: int = 0
    tasks: list[TaskOut] = Field(default_factory=list)
    warnings: list[CommitWarning] = Field(default_factory=list)
    errors: list[CommitError] = Field(default_factory=list)


class DraftBatch(BaseModel):
    """What a source hands back for review."""

    source_provider: str
    drafts: list[DraftTask]
    warnings: list[str] = Field(default_factory=list)
    #: Whatever the adapter's optional ``describe()`` returned — CSV puts its
    #: detected columns and chosen mapping here. Opaque to core.
    meta: dict = Field(default_factory=dict)
