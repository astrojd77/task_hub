"""Configurable dropdowns and per-source defaults.

Three jobs, all of them read-mostly:

* **resolve** — what options does each field offer right now?
* **validate** — is a reviewed value one of them?
* **apply defaults** — pre-fill a draft's blanks for its import flow.

## Why builtin options are constrained

Builtin fields (status, priority, criticality, impact_size) can be relabelled,
reordered and subset, but their *value set* stays the canonical enum. Two things
key off those values and would silently degrade otherwise:

* the watch score's weight tables — an unrecognised criticality scores 0
* every adapter's mapping table — ``Sev 1 -> critical`` and the rest

So a value can be hidden from the dropdown, but not invented. Custom fields have
neither coupling and are fully user-defined.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ENUM_CATALOG
from app.models.config import BUILTIN_FIELD_KEYS, FieldConfig, SourceDefault
from app.models.task import utcnow
from app.schemas.task import DraftTask

#: Human labels for the builtin fields, used when seeding.
BUILTIN_LABELS = {
    "status": "Status",
    "priority": "Priority",
    "criticality": "Criticality",
    "impact_size": "Impact",
}

#: Fields a source default may set. Deliberately wider than the dropdowns —
#: pre-filling "project" for the email flow is exactly the sort of thing this
#: feature is for.
DEFAULTABLE_EXTRA_KEYS = ("project", "assignee")


class FieldConfigError(ValueError):
    """The configuration itself is invalid."""


def _default_options(field_key: str) -> list[dict[str, str]]:
    return [{"value": v, "label": v.replace("_", " ")} for v in ENUM_CATALOG.get(field_key, [])]


def ensure_builtin_fields(db: Session) -> list[FieldConfig]:
    """Materialise a FieldConfig row for each builtin field, once.

    Seeded lazily from the code enums rather than in the migration, so the
    canonical scales have exactly one source of truth and the SQL cannot drift
    away from them.
    """
    existing = {
        fc.field_key: fc
        for fc in db.execute(
            select(FieldConfig).where(FieldConfig.field_key.in_(BUILTIN_FIELD_KEYS))
        ).scalars()
    }

    created = False
    for index, key in enumerate(BUILTIN_FIELD_KEYS):
        if key in existing:
            continue
        config = FieldConfig(
            field_key=key,
            label=BUILTIN_LABELS[key],
            kind="builtin",
            options=_default_options(key),
            enabled=True,
            # status and priority always have a value; the other two are what
            # the review popup exists to capture, so neither is required here.
            is_required=False,
            sort_order=index,
        )
        db.add(config)
        existing[key] = config
        created = True

    if created:
        db.commit()

    return list_fields(db)


def list_fields(db: Session, *, enabled_only: bool = False) -> list[FieldConfig]:
    stmt = select(FieldConfig).order_by(FieldConfig.sort_order, FieldConfig.field_key)
    if enabled_only:
        stmt = stmt.where(FieldConfig.enabled.is_(True))
    return list(db.execute(stmt).scalars())


def get_field(db: Session, field_key: str) -> FieldConfig | None:
    return db.execute(
        select(FieldConfig).where(FieldConfig.field_key == field_key)
    ).scalar_one_or_none()


def custom_fields(db: Session, *, enabled_only: bool = True) -> list[FieldConfig]:
    return [f for f in list_fields(db, enabled_only=enabled_only) if f.kind == "custom"]


# -- writes --------------------------------------------------------------


def _clean_options(options: list[dict[str, Any]]) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()

    for option in options or []:
        value = str(option.get("value", "")).strip()
        if not value:
            raise FieldConfigError("an option cannot have a blank value")
        if value in seen:
            raise FieldConfigError(f"duplicate option value: {value!r}")
        seen.add(value)
        cleaned.append({"value": value, "label": str(option.get("label") or value).strip()})

    return cleaned


def upsert_field(
    db: Session,
    *,
    field_key: str,
    label: str,
    options: list[dict[str, Any]],
    kind: str = "custom",
    enabled: bool = True,
    is_required: bool = False,
    sort_order: int | None = None,
) -> FieldConfig:
    field_key = field_key.strip().lower().replace(" ", "_")
    if not field_key:
        raise FieldConfigError("field_key is required")

    existing = get_field(db, field_key)
    cleaned = _clean_options(options)

    # Decided from the canonical list, not from the stored row: the builtin
    # rows are seeded lazily, so a PUT that arrives before the first GET would
    # otherwise create "criticality" as a *custom* field and quietly bypass the
    # constraint below.
    builtin = field_key in BUILTIN_FIELD_KEYS
    if builtin:
        # Relabel, reorder, subset — but the value set stays canonical, because
        # the watch weights and every adapter's mapping table key off it.
        canonical = set(ENUM_CATALOG.get(field_key, []))
        invented = [o["value"] for o in cleaned if o["value"] not in canonical]
        if invented:
            raise FieldConfigError(
                f"{field_key!r} is a builtin scale — {invented} are not canonical values. "
                f"Allowed: {sorted(canonical)}. You can hide, relabel and reorder them, "
                "but adding a value needs a code change so the watch weights and the "
                "adapter mappings stay in step."
            )
        if not cleaned:
            raise FieldConfigError(f"{field_key!r} must keep at least one option")

    if existing is None:
        if not cleaned:
            raise FieldConfigError("a new field needs at least one option")
        existing = FieldConfig(
            field_key=field_key,
            kind="builtin" if builtin else kind,
            sort_order=sort_order if sort_order is not None else _next_sort_order(db),
        )
        db.add(existing)
    elif sort_order is not None:
        existing.sort_order = sort_order

    existing.label = label.strip() or field_key
    existing.options = cleaned
    existing.enabled = enabled
    existing.is_required = is_required
    existing.updated_at = utcnow()

    db.commit()
    db.refresh(existing)
    return existing


def _next_sort_order(db: Session) -> int:
    fields = list_fields(db)
    return (max((f.sort_order for f in fields), default=-1)) + 1


def delete_field(db: Session, field_key: str) -> None:
    field = get_field(db, field_key)
    if field is None:
        return
    if field.is_builtin:
        raise FieldConfigError(
            f"{field_key!r} is a builtin field backed by a real column and cannot be deleted. "
            "Disable it instead to hide it from the UI."
        )
    # Values already written to tasks.custom_fields are left alone: deleting a
    # field definition should not silently rewrite historical task data.
    db.execute(SourceDefault.__table__.delete().where(SourceDefault.field_key == field_key))
    db.delete(field)
    db.commit()


# -- per-source defaults -------------------------------------------------


def list_defaults(db: Session, source_provider: str | None = None) -> list[SourceDefault]:
    stmt = select(SourceDefault).order_by(SourceDefault.source_provider, SourceDefault.field_key)
    if source_provider:
        stmt = stmt.where(SourceDefault.source_provider == source_provider)
    return list(db.execute(stmt).scalars())


def set_default(
    db: Session, source_provider: str, field_key: str, value: str | None
) -> SourceDefault | None:
    """Set or clear one field's default for one import flow."""
    existing = db.execute(
        select(SourceDefault).where(
            SourceDefault.source_provider == source_provider,
            SourceDefault.field_key == field_key,
        )
    ).scalar_one_or_none()

    if value is None or not str(value).strip():
        if existing is not None:
            db.delete(existing)
            db.commit()
        return None

    value = str(value).strip()
    field = get_field(db, field_key)
    if field is not None and value not in field.values:
        raise FieldConfigError(f"{value!r} is not an option for {field_key!r} — {field.values}")
    if field is None and field_key not in DEFAULTABLE_EXTRA_KEYS:
        raise FieldConfigError(f"unknown field: {field_key!r}")

    if existing is None:
        existing = SourceDefault(source_provider=source_provider, field_key=field_key, value=value)
        db.add(existing)
    else:
        existing.value = value
        existing.updated_at = utcnow()

    db.commit()
    db.refresh(existing)
    return existing


def apply_defaults(db: Session, drafts: list[DraftTask], source_provider: str) -> None:
    """Pre-fill each draft's blanks with this flow's defaults.

    Runs before review, never after. Only fills fields the source left empty —
    a source is authoritative for what it actually knows, and a default that
    overwrote a real value would be worse than no default at all. Every filled
    field is announced in the draft's warnings so the reviewer can see it was
    the configuration talking, not the source.
    """
    defaults = list_defaults(db, source_provider)
    if not defaults or not drafts:
        return

    field_kinds = {f.field_key: f.kind for f in list_fields(db)}

    for draft in drafts:
        applied: list[str] = []

        for default in defaults:
            key, value = default.field_key, default.value

            if field_kinds.get(key) == "custom":
                if draft.custom_fields.get(key):
                    continue
                draft.custom_fields = {**draft.custom_fields, key: value}
            else:
                if getattr(draft, key, None) is not None:
                    continue
                try:
                    setattr(draft, key, value)
                except ValueError:
                    # A default that no longer validates — the option was
                    # removed after it was set. Skip it rather than failing the
                    # whole import.
                    continue

            applied.append(f"{key}={value}")

        if applied:
            draft.warnings.append(f"defaults applied for {source_provider}: {', '.join(applied)}")


# -- validation ----------------------------------------------------------


def validate_custom_fields(db: Session, values: dict[str, Any]) -> list[str]:
    """Check reviewed custom-field values against the configured options.

    Returns error messages; empty means valid. Custom fields live in a JSON
    column, so the database enforces nothing here — this is the enforcement.
    """
    if not values:
        values = {}

    errors: list[str] = []
    configured = {f.field_key: f for f in custom_fields(db, enabled_only=False)}

    for key, value in values.items():
        field = configured.get(key)
        if field is None:
            errors.append(f"unknown custom field {key!r}")
            continue
        if value in (None, ""):
            continue
        if str(value) not in field.values:
            errors.append(f"{value!r} is not an option for {field.label!r} — {field.values}")

    for field in configured.values():
        if field.enabled and field.is_required and not values.get(field.field_key):
            errors.append(f"{field.label} is required")

    return errors
