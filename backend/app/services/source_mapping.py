"""Per-source field mapping: which input feeds a field, and how values translate.

This is the layer that makes every import flow configurable in the same way,
whatever it is importing from. It is deliberately thin: core still knows nothing
about CSV columns, Jira field ids or email parts. It only knows that a source
maps *something* onto a canonical field, and hands the adapter a resolver.

Everything here is an **override**. An adapter's built-in header aliases and
value tables still apply wherever configuration is silent, so a fresh install
imports sensibly with no mapping configured at all — and a mapping only has to
describe the parts that differ from the defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.config import SourceMapping
from app.models.task import utcnow

#: Reserved config key under which build_batch hands the resolver to an adapter.
MAPPING_CONFIG_KEY = "_mapping"


class SourceMappingError(ValueError):
    """The mapping itself is invalid."""


@dataclass(frozen=True)
class FieldMapping:
    source_expr: str | None = None
    #: Lowercased native value -> canonical value.
    value_map: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedMapping:
    """What an adapter is handed. Read-only, and safe to use when empty."""

    source_provider: str
    fields: dict[str, FieldMapping] = field(default_factory=dict)

    def input_for(self, field_key: str, fallback: str | None = None) -> str | None:
        """Which input feeds this field, or the adapter's own default."""
        mapping = self.fields.get(field_key)
        if mapping and mapping.source_expr:
            return mapping.source_expr
        return fallback

    def translate(self, field_key: str, native_value: str | None) -> tuple[str | None, bool]:
        """Apply the configured value rules.

        Returns ``(canonical_value, matched)``. ``matched`` is False when there
        is no configured rule for this value, which tells the adapter to fall
        back to its own table rather than treating the value as unmappable —
        the difference between "configuration is silent" and "configuration
        says this is off-scale".
        """
        if native_value is None:
            return None, False
        mapping = self.fields.get(field_key)
        if not mapping or not mapping.value_map:
            return None, False
        hit = mapping.value_map.get(str(native_value).strip().lower())
        return (hit, True) if hit else (None, False)

    def has_value_rules(self, field_key: str) -> bool:
        mapping = self.fields.get(field_key)
        return bool(mapping and mapping.value_map)


EMPTY_MAPPING = ResolvedMapping(source_provider="")


def resolve(db: Session, source_provider: str) -> ResolvedMapping:
    rows = db.execute(
        select(SourceMapping).where(SourceMapping.source_provider == source_provider)
    ).scalars()

    return ResolvedMapping(
        source_provider=source_provider,
        fields={
            row.field_key: FieldMapping(
                source_expr=row.source_expr,
                value_map={
                    str(k).strip().lower(): str(v)
                    for k, v in (row.value_map or {}).items()
                    if str(k).strip() and str(v).strip()
                },
            )
            for row in rows
        },
    )


def mapping_from_config(config: dict[str, Any]) -> ResolvedMapping:
    """Read the resolver an adapter was handed, tolerating its absence.

    Adapters are also used directly in tests without a database, so this must
    never require one.
    """
    resolved = config.get(MAPPING_CONFIG_KEY)
    return resolved if isinstance(resolved, ResolvedMapping) else EMPTY_MAPPING


# -- writes --------------------------------------------------------------


def list_mappings(db: Session, source_provider: str | None = None) -> list[SourceMapping]:
    stmt = select(SourceMapping).order_by(SourceMapping.source_provider, SourceMapping.field_key)
    if source_provider:
        stmt = stmt.where(SourceMapping.source_provider == source_provider)
    return list(db.execute(stmt).scalars())


def set_mapping(
    db: Session,
    source_provider: str,
    field_key: str,
    source_expr: str | None,
    value_map: dict[str, str] | None = None,
) -> SourceMapping | None:
    """Set or clear one field's mapping for one import flow."""
    cleaned_expr = (source_expr or "").strip() or None
    cleaned_values = {
        str(k).strip().lower(): str(v).strip()
        for k, v in (value_map or {}).items()
        if str(k).strip() and str(v).strip()
    }

    existing = db.execute(
        select(SourceMapping).where(
            SourceMapping.source_provider == source_provider,
            SourceMapping.field_key == field_key,
        )
    ).scalar_one_or_none()

    # Nothing configured either way — remove the row rather than storing an
    # empty override that reads as "configured" in the UI.
    if cleaned_expr is None and not cleaned_values:
        if existing is not None:
            db.delete(existing)
            db.commit()
        return None

    if existing is None:
        existing = SourceMapping(
            source_provider=source_provider,
            field_key=field_key,
            source_expr=cleaned_expr,
            value_map=cleaned_values,
        )
        db.add(existing)
    else:
        existing.source_expr = cleaned_expr
        existing.value_map = cleaned_values
        existing.updated_at = utcnow()

    db.commit()
    db.refresh(existing)
    return existing


def add_value_rule(
    db: Session, source_provider: str, field_key: str, native_value: str, canonical: str
) -> SourceMapping:
    """Add one value rule, keeping the rest of the field's mapping intact.

    Distinct from ``set_mapping``, which replaces the whole value map. The
    review screen adds rules one at a time as it meets values it could not
    translate, and must not clobber what is already configured — or the input
    column, which is often the only thing set.
    """
    native = str(native_value).strip()
    canonical = str(canonical).strip()
    if not native or not canonical:
        raise SourceMappingError("a rule needs both a value and what it maps to")

    existing = db.execute(
        select(SourceMapping).where(
            SourceMapping.source_provider == source_provider,
            SourceMapping.field_key == field_key,
        )
    ).scalar_one_or_none()

    merged = {**((existing.value_map if existing else None) or {}), native.lower(): canonical}

    if existing is None:
        existing = SourceMapping(
            source_provider=source_provider,
            field_key=field_key,
            source_expr=None,
            value_map=merged,
        )
        db.add(existing)
    else:
        # Reassign rather than mutate: PortableJSON tracks by identity, so an
        # in-place update would not be flushed.
        existing.value_map = merged
        existing.updated_at = utcnow()

    db.commit()
    db.refresh(existing)
    return existing


def replace_mappings(
    db: Session, source_provider: str, mappings: dict[str, dict[str, Any]]
) -> list[SourceMapping]:
    """Save a whole flow's mapping in one call, as the Config screen does."""
    for field_key, spec in mappings.items():
        set_mapping(
            db,
            source_provider,
            field_key,
            spec.get("source_expr"),
            spec.get("value_map"),
        )
    return list_mappings(db, source_provider)


def translate_enum(
    mapping: ResolvedMapping,
    field_key: str,
    native_value: str | None,
    builtin_table: dict[str, Any],
    label: str,
    warnings: list[str],
    unmapped: list[dict[str, str]] | None = None,
) -> Any | None:
    """Native value -> canonical, configuration first, adapter table second.

    Shared by every adapter because the *precedence* is a product decision, not
    a platform one: what the user configured wins, the adapter's built-in
    aliases fill the gaps, and anything left over warns rather than being
    guessed at. A blank field the reviewer can see beats a wrong one they
    cannot.
    """
    if native_value is None or not str(native_value).strip():
        return None

    configured, matched = mapping.translate(field_key, native_value)
    if matched:
        return configured

    hit = builtin_table.get(str(native_value).strip().lower())
    if hit is None:
        warnings.append(f"{label} {native_value!r} is not on the scale")
        if unmapped is not None:
            unmapped.append(
                {
                    "field_key": field_key,
                    "label": label,
                    "native_value": str(native_value).strip(),
                }
            )
    return hit
