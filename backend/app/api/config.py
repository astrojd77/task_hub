"""Field configuration: dropdown options and per-source defaults.

Backs the Config screen. Everything here is read by the review UI and the
filters, so a field added here shows up in those without a code change.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.providers import registry
from app.services.field_config import (
    FieldConfigError,
    delete_field,
    ensure_builtin_fields,
    list_defaults,
    list_fields,
    set_default,
    upsert_field,
)
from app.services.source_mapping import (
    SourceMappingError,
    add_value_rule,
    list_mappings,
    replace_mappings,
)

router = APIRouter(prefix="/config", tags=["config"])


class Option(BaseModel):
    value: str
    label: str | None = None


class FieldOut(BaseModel):
    field_key: str
    label: str
    kind: str
    options: list[Option]
    enabled: bool
    is_required: bool
    sort_order: int
    #: Builtin scales can be relabelled, reordered and subset, but their value
    #: set is fixed — the watch weights and the adapter mappings key off it.
    values_locked: bool


class FieldIn(BaseModel):
    field_key: str
    label: str
    options: list[Option] = Field(default_factory=list)
    enabled: bool = True
    is_required: bool = False
    sort_order: int | None = None


class DefaultOut(BaseModel):
    source_provider: str
    field_key: str
    value: str


class DefaultIn(BaseModel):
    source_provider: str
    field_key: str
    #: null clears the default.
    value: str | None = None


class MappingSpec(BaseModel):
    source_expr: str | None = None
    value_map: dict[str, str] = Field(default_factory=dict)


class MappingOut(BaseModel):
    source_provider: str
    field_key: str
    #: Adapter-specific: a CSV column, a Jira field id, an email part.
    source_expr: str | None
    #: Native value (lowercased) -> canonical value.
    value_map: dict[str, str]


class MappingIn(BaseModel):
    source_provider: str
    #: field_key -> {source_expr, value_map}. A field with neither is cleared.
    mappings: dict[str, MappingSpec]


class ValueRuleIn(BaseModel):
    source_provider: str
    field_key: str
    #: Exactly what the source said.
    native_value: str
    #: The canonical value it should become.
    value: str


class InputOut(BaseModel):
    key: str
    label: str
    #: A sample value from the file or issue, so the choice is obvious.
    hint: str | None = None


class ConfigOut(BaseModel):
    fields: list[FieldOut]
    defaults: list[DefaultOut]
    #: Registered source ids, so the UI can offer a defaults tab per flow.
    sources: list[str]
    #: Fields a default may target that are not dropdowns.
    defaultable_extra_keys: list[str]
    mappings: list[MappingOut]
    #: Every canonical field a mapping can target, in display order.
    mappable_fields: list[FieldOut]


def _to_out(field) -> FieldOut:
    return FieldOut(
        field_key=field.field_key,
        label=field.label,
        kind=field.kind,
        options=[Option(**o) for o in (field.options or [])],
        enabled=field.enabled,
        is_required=field.is_required,
        sort_order=field.sort_order,
        values_locked=field.is_builtin,
    )


@router.get("", response_model=ConfigOut)
def get_config(db: Session = Depends(get_db)) -> ConfigOut:
    from app.services.field_config import DEFAULTABLE_EXTRA_KEYS

    # Seeds the builtin rows on first call, from the canonical enums.
    ensure_builtin_fields(db)

    return ConfigOut(
        fields=[_to_out(f) for f in list_fields(db)],
        defaults=[
            DefaultOut(source_provider=d.source_provider, field_key=d.field_key, value=d.value)
            for d in list_defaults(db)
        ],
        sources=[s.id for s in registry.sources()],
        defaultable_extra_keys=list(DEFAULTABLE_EXTRA_KEYS),
        mappings=[
            MappingOut(
                source_provider=m.source_provider,
                field_key=m.field_key,
                source_expr=m.source_expr,
                value_map=m.value_map or {},
            )
            for m in list_mappings(db)
        ],
        mappable_fields=[_to_out(f) for f in list_fields(db)],
    )


@router.post("/mappings/rule", response_model=MappingOut)
def add_rule(payload: ValueRuleIn, db: Session = Depends(get_db)) -> MappingOut:
    """Teach one value, from the review screen.

    Merges into the field's existing rules rather than replacing them, so
    mapping a value never disturbs the input column or the rules already there.
    """
    try:
        registry.source(payload.source_provider)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        saved = add_value_rule(
            db, payload.source_provider, payload.field_key, payload.native_value, payload.value
        )
    except SourceMappingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return MappingOut(
        source_provider=saved.source_provider,
        field_key=saved.field_key,
        source_expr=saved.source_expr,
        value_map=saved.value_map or {},
    )


@router.put("/mappings", response_model=list[MappingOut])
def put_mappings(payload: MappingIn, db: Session = Depends(get_db)) -> list[MappingOut]:
    """Save a whole flow's mapping at once, as the Config screen does."""
    try:
        registry.source(payload.source_provider)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    saved = replace_mappings(
        db,
        payload.source_provider,
        {k: v.model_dump() for k, v in payload.mappings.items()},
    )
    return [
        MappingOut(
            source_provider=m.source_provider,
            field_key=m.field_key,
            source_expr=m.source_expr,
            value_map=m.value_map or {},
        )
        for m in saved
    ]


@router.put("/fields/{field_key}", response_model=FieldOut)
def put_field(field_key: str, payload: FieldIn, db: Session = Depends(get_db)) -> FieldOut:
    if payload.field_key != field_key:
        raise HTTPException(status_code=400, detail="field_key in the body must match the path")
    try:
        field = upsert_field(
            db,
            field_key=field_key,
            label=payload.label,
            options=[o.model_dump() for o in payload.options],
            enabled=payload.enabled,
            is_required=payload.is_required,
            sort_order=payload.sort_order,
        )
    except FieldConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(field)


@router.delete("/fields/{field_key}", status_code=204)
def remove_field(field_key: str, db: Session = Depends(get_db)) -> None:
    try:
        delete_field(db, field_key)
    except FieldConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/defaults", response_model=DefaultOut | None)
def put_default(payload: DefaultIn, db: Session = Depends(get_db)) -> DefaultOut | None:
    try:
        registry.source(payload.source_provider)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        default = set_default(db, payload.source_provider, payload.field_key, payload.value)
    except FieldConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if default is None:
        return None
    return DefaultOut(
        source_provider=default.source_provider,
        field_key=default.field_key,
        value=default.value,
    )
