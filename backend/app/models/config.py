"""User-configurable fields, per-source mappings and per-source defaults.

Three tables, three jobs:

``FieldConfig``    what options a dropdown offers, and what it is called.
``SourceMapping``  which input feeds a field, and how its values translate.
``SourceDefault``  what an import flow pre-fills before the user reviews it.

Fields come in two kinds:

* **builtin** — backed by a real column on ``tasks`` (status, priority,
  criticality, impact_size). Their options are configurable, but the column
  they write to is not.
* **custom** — user-invented (Type, Platform, …), stored in
  ``tasks.custom_fields``. Adding one needs no migration, which is the whole
  point; the trade-off is that the database enforces nothing about their
  values, so ``services/field_config.py`` does.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import PortableJSON, UTCDateTime
from app.models.task import new_uuid, utcnow

#: Builtin fields map onto these columns of `tasks`.
BUILTIN_FIELD_KEYS = ("status", "priority", "criticality", "impact_size")


class FieldConfig(Base):
    __tablename__ = "field_configs"
    __table_args__ = (UniqueConstraint("field_key", name="uq_field_configs_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)

    #: "criticality", "type", "platform" — also the key under
    #: ``tasks.custom_fields`` for custom fields.
    field_key: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)

    #: [{"value": "bug", "label": "Bug"}, ...] — order is display order.
    options: Mapped[list] = mapped_column(PortableJSON, nullable=False, default=list)

    #: Hidden from the review UI and the filters when false. Builtin fields are
    #: never truly removed; the column still exists and still validates.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Blocks commit when unset, the same way a blank summary does.
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    @property
    def is_builtin(self) -> bool:
        return self.kind == "builtin"

    @property
    def values(self) -> list[str]:
        return [o["value"] for o in (self.options or []) if o.get("value")]

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<FieldConfig {self.field_key!r} {self.kind} {len(self.options or [])} options>"


class SourceDefault(Base):
    """What an import flow pre-fills, before the user reviews it.

    Applied only where the source left the field blank — a source is
    authoritative for what it actually knows, and a default must never
    overwrite that. The reviewer still sees and can change everything, so this
    stays consistent with review-before-commit.
    """

    __tablename__ = "source_defaults"
    __table_args__ = (UniqueConstraint("source_provider", "field_key", name="uq_source_defaults"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)

    #: "csv" | "jira" | "email" — a registered source id.
    source_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    field_key: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[str] = mapped_column(String(200), nullable=False)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<SourceDefault {self.source_provider}.{self.field_key}={self.value!r}>"


class SourceMapping(Base):
    """How one import flow feeds one canonical field.

    Two halves, either of which may be used alone:

    ``source_expr``  which input feeds the field. What the string *means* is the
                     adapter's business — a CSV column header, a Jira field id,
                     an email part. Core never interprets it.
    ``value_map``    how that input's values translate into canonical ones,
                     e.g. ``{"sev 1": "critical"}``. Keys are lowercased on the
                     way in so matching is case-insensitive.

    Both are overrides. An adapter's built-in aliases and value tables still
    apply wherever configuration is silent, so a fresh install works with no
    mapping configured at all.
    """

    __tablename__ = "source_mappings"
    __table_args__ = (UniqueConstraint("source_provider", "field_key", name="uq_source_mappings"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)

    source_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    field_key: Mapped[str] = mapped_column(String(50), nullable=False)
    source_expr: Mapped[str | None] = mapped_column(String(200), nullable=True)
    value_map: Mapped[dict] = mapped_column(PortableJSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<SourceMapping {self.source_provider}.{self.field_key} <- {self.source_expr!r}>"
