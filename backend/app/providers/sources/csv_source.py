"""CSV source.

Bulk import with explicit column mapping. Two responsibilities, split across
the protocol's two methods:

* ``fetch``    — read the file, apply the column mapping, emit one RawItem per
                 row carrying both the original row (provenance) and the mapped
                 cells.
* ``to_draft`` — translate those cells into the canonical vocabulary.

The value tables below are this adapter's private business. A CSV that says
"Sev 1" or "P0" or "T-shirt: XL" is CSV's problem to translate; core only ever
sees canonical enum values.
"""

from __future__ import annotations

import csv
import hashlib
import io
from typing import Any

from app.core.enums import Criticality, ImpactSize, Priority, TaskStatus
from app.core.parsing import clean_text, parse_date, split_labels
from app.providers.base import ProviderError, RawItem, UploadedFile
from app.providers.registry import source
from app.schemas.task import DraftTask
from app.services.source_mapping import EMPTY_MAPPING, mapping_from_config, translate_enum

#: Canonical field -> header spellings we will auto-map on upload. The user can
#: always override the suggestion in the mapping UI.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "summary": ("summary", "title", "name", "task", "subject", "item", "work item"),
    "description": ("description", "details", "detail", "notes", "note", "body", "comments"),
    "status": ("status", "state", "stage"),
    "priority": ("priority", "urgency", "prio"),
    "criticality": ("criticality", "severity", "sev", "risk"),
    "impact_size": ("impact_size", "impact", "size", "blast radius", "scope", "t-shirt"),
    "due_date": ("due_date", "due", "duedate", "due date", "deadline", "target date", "end date"),
    "assignee": ("assignee", "owner", "assigned to", "responsible", "dri"),
    "project": ("project", "epic", "workstream", "initiative", "program", "team"),
    "labels": ("labels", "label", "tags", "tag", "categories"),
    "source_ref": ("id", "key", "ref", "reference", "ticket", "external id"),
}

_STATUS_VALUES: dict[str, TaskStatus] = {
    "todo": TaskStatus.TODO,
    "to do": TaskStatus.TODO,
    "to-do": TaskStatus.TODO,
    "new": TaskStatus.TODO,
    "open": TaskStatus.TODO,
    "backlog": TaskStatus.TODO,
    "not started": TaskStatus.TODO,
    "in progress": TaskStatus.IN_PROGRESS,
    "in-progress": TaskStatus.IN_PROGRESS,
    "inprogress": TaskStatus.IN_PROGRESS,
    "in_progress": TaskStatus.IN_PROGRESS,
    "doing": TaskStatus.IN_PROGRESS,
    "wip": TaskStatus.IN_PROGRESS,
    "active": TaskStatus.IN_PROGRESS,
    "started": TaskStatus.IN_PROGRESS,
    "blocked": TaskStatus.BLOCKED,
    "on hold": TaskStatus.BLOCKED,
    "waiting": TaskStatus.BLOCKED,
    "impeded": TaskStatus.BLOCKED,
    "done": TaskStatus.DONE,
    "complete": TaskStatus.DONE,
    "completed": TaskStatus.DONE,
    "closed": TaskStatus.DONE,
    "resolved": TaskStatus.DONE,
    "shipped": TaskStatus.DONE,
}

_PRIORITY_VALUES: dict[str, Priority] = {
    "low": Priority.LOW,
    "p4": Priority.LOW,
    "p3": Priority.LOW,
    "minor": Priority.LOW,
    "trivial": Priority.LOW,
    "medium": Priority.MEDIUM,
    "med": Priority.MEDIUM,
    "normal": Priority.MEDIUM,
    "moderate": Priority.MEDIUM,
    "p2": Priority.MEDIUM,
    "high": Priority.HIGH,
    "major": Priority.HIGH,
    "p1": Priority.HIGH,
    "urgent": Priority.URGENT,
    "critical": Priority.URGENT,
    "blocker": Priority.URGENT,
    "highest": Priority.URGENT,
    "p0": Priority.URGENT,
}

_CRITICALITY_VALUES: dict[str, Criticality] = {
    "low": Criticality.LOW,
    "sev4": Criticality.LOW,
    "sev 4": Criticality.LOW,
    "4": Criticality.LOW,
    "medium": Criticality.MEDIUM,
    "med": Criticality.MEDIUM,
    "moderate": Criticality.MEDIUM,
    "sev3": Criticality.MEDIUM,
    "sev 3": Criticality.MEDIUM,
    "3": Criticality.MEDIUM,
    "high": Criticality.HIGH,
    "sev2": Criticality.HIGH,
    "sev 2": Criticality.HIGH,
    "2": Criticality.HIGH,
    "critical": Criticality.CRITICAL,
    "sev1": Criticality.CRITICAL,
    "sev 1": Criticality.CRITICAL,
    "1": Criticality.CRITICAL,
    "severe": Criticality.CRITICAL,
}

_IMPACT_VALUES: dict[str, ImpactSize] = {
    "xs": ImpactSize.XS,
    "extra small": ImpactSize.XS,
    "tiny": ImpactSize.XS,
    "s": ImpactSize.S,
    "small": ImpactSize.S,
    "m": ImpactSize.M,
    "medium": ImpactSize.M,
    "med": ImpactSize.M,
    "l": ImpactSize.L,
    "large": ImpactSize.L,
    "big": ImpactSize.L,
    "xl": ImpactSize.XL,
    "extra large": ImpactSize.XL,
    "huge": ImpactSize.XL,
}

#: Every canonical field the mapping UI can bind a column to.
MAPPABLE_FIELDS: tuple[str, ...] = tuple(COLUMN_ALIASES)

_MAX_ROWS = 5000


def _normalize_header(header: str) -> str:
    return header.strip().lower().replace("_", " ").replace("-", " ").strip()


def suggest_mapping(columns: list[str]) -> dict[str, str]:
    """Guess canonical_field -> column. Exact alias match wins over substring."""
    normalized = {col: _normalize_header(col) for col in columns}
    mapping: dict[str, str] = {}
    taken: set[str] = set()

    for field, aliases in COLUMN_ALIASES.items():
        alias_set = {_normalize_header(a) for a in aliases}
        for col, norm in normalized.items():
            if col not in taken and norm in alias_set:
                mapping[field] = col
                taken.add(col)
                break

    for field, aliases in COLUMN_ALIASES.items():
        if field in mapping:
            continue
        alias_set = {_normalize_header(a) for a in aliases}
        for col, norm in normalized.items():
            if col in taken:
                continue
            if any(a in norm or norm in a for a in alias_set):
                mapping[field] = col
                taken.add(col)
                break

    return mapping


def read_csv(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """Decode and parse. Returns (columns, rows)."""
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 decodes any byte string
        raise ProviderError("could not decode the file as text")

    if not text.strip():
        raise ProviderError("the file is empty")

    sample = text[:8192]
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ProviderError("the file has no header row")

    columns = [c.strip() for c in reader.fieldnames if c and c.strip()]
    if not columns:
        raise ProviderError("the file has no usable column headers")

    rows: list[dict[str, str]] = []
    for row in reader:
        # DictReader puts surplus cells under a None key; drop it.
        clean = {(k.strip() if k else k): v for k, v in row.items() if k is not None and k.strip()}
        if any(str(v).strip() for v in clean.values() if v is not None):
            rows.append(clean)
        if len(rows) > _MAX_ROWS:
            raise ProviderError(f"file has more than {_MAX_ROWS} rows — split it and retry")

    return columns, rows


def row_hash(row: dict[str, str]) -> str:
    """Idempotency key for a row without its own id.

    Hashes the *original* row, never the reviewed values — so editing a task in
    the review screen and re-importing the same file still updates that task
    rather than creating a second one.
    """
    payload = "\x1f".join(
        f"{k}\x1e{'' if v is None else str(v).strip()}" for k, v in sorted(row.items())
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@source
class CsvSource:
    id = "csv"
    display_name = "CSV file"

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file": {"type": "file", "accept": ".csv,.tsv,text/csv", "required": True},
                "mapping": {
                    "type": "object",
                    "description": "canonical field -> CSV column header",
                    "fields": list(MAPPABLE_FIELDS),
                },
            },
            "required": ["file"],
        }

    def describe(self, config: dict[str, Any]) -> dict[str, Any]:
        """Tell the review UI what columns exist and how they were mapped.

        Re-reads the file rather than threading state out of ``fetch``; the
        parse is cheap at this file size and it keeps ``fetch`` matching the
        protocol exactly.
        """
        upload = config.get("file")
        if not isinstance(upload, UploadedFile):
            return {}
        columns, rows = read_csv(upload.content)
        supplied = config.get("mapping") or {}
        return {
            "filename": upload.filename,
            "columns": columns,
            "row_count": len(rows),
            "mappable_fields": list(MAPPABLE_FIELDS),
            "mapping": {
                f: c
                for f, c in (supplied or suggest_mapping(columns)).items()
                if c in columns and f in COLUMN_ALIASES
            },
            "suggested_mapping": suggest_mapping(columns),
        }

    def mappable_inputs(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """The uploaded file's columns, with a sample value each.

        Only knowable once a file is in hand, which is why the mapping screen
        lets you save the mapping straight from the import flow — that is the
        moment the real column names are on screen.
        """
        upload = config.get("file")
        if not isinstance(upload, UploadedFile):
            return []

        columns, rows = read_csv(upload.content)
        first = rows[0] if rows else {}
        return [
            {"key": column, "label": column, "hint": clean_text(first.get(column))}
            for column in columns
        ]

    def fetch(self, config: dict[str, Any]) -> list[RawItem]:
        upload = config.get("file")
        if not isinstance(upload, UploadedFile):
            raise ProviderError("no CSV file was provided")

        columns, rows = read_csv(upload.content)
        # Three layers, most specific first: what this request asked for, then
        # the mapping saved for the CSV flow, then header auto-detection. The
        # saved layer is what makes a recurring import a one-click job.
        saved = mapping_from_config(config)
        saved_columns = {
            field_key: mapping.source_expr
            for field_key, mapping in saved.fields.items()
            if mapping.source_expr
        }
        mapping = config.get("mapping") or saved_columns or suggest_mapping(columns)
        # Drop anything pointing at a column this file does not have. Custom
        # field keys are kept: the adapter does not know what "type" is, only
        # that something asked for a column, and _custom_fields sorts it out.
        mapping = {f: c for f, c in mapping.items() if c in columns}

        ref_column = mapping.get("source_ref")
        items: list[RawItem] = []
        for row in rows:
            explicit_ref = clean_text(row.get(ref_column)) if ref_column else None
            items.append(
                RawItem(
                    source_ref=explicit_ref or row_hash(row),
                    payload={
                        "row": row,
                        "mapping": mapping,
                        "configured": saved,
                        "ref_from": "column" if explicit_ref else "row-hash",
                    },
                )
            )
        return items

    def to_draft(self, raw: RawItem) -> DraftTask:
        row: dict[str, str] = raw.payload["row"]
        mapping: dict[str, str] = raw.payload["mapping"]
        configured = raw.payload.get("configured") or EMPTY_MAPPING
        warnings: list[str] = []

        def cell(field: str) -> str | None:
            column = mapping.get(field)
            return clean_text(row.get(column)) if column else None

        def to_enum(field: str, table: dict, label: str):
            # Configured value rules win; the tables above fill the gaps.
            return translate_enum(configured, field, cell(field), table, label, warnings)

        summary = cell("summary")
        if summary is None:
            warnings.append("no summary in this row — required before commit")

        due_date, date_warning = parse_date(cell("due_date"))
        if date_warning:
            warnings.append(date_warning)

        status = to_enum("status", _STATUS_VALUES, "status")
        priority = to_enum("priority", _PRIORITY_VALUES, "priority")

        return DraftTask(
            summary=summary or "",
            description=cell("description"),
            status=status or TaskStatus.TODO,
            priority=priority or Priority.MEDIUM,
            criticality=to_enum("criticality", _CRITICALITY_VALUES, "criticality"),
            impact_size=to_enum("impact_size", _IMPACT_VALUES, "impact"),
            due_date=due_date,
            assignee=cell("assignee"),
            project=cell("project"),
            labels=split_labels(cell("labels")),
            custom_fields=self._custom_fields(row, mapping, configured, warnings),
            source_provider=self.id,
            source_ref=raw.source_ref,
            raw_payload=row,
            warnings=warnings,
        )

    @staticmethod
    def _custom_fields(row, mapping, configured, warnings) -> dict[str, str]:
        """Any mapped field that is not one of ours is a configured custom field.

        The adapter does not need to know what Type or Platform are — only that
        something asked for a column and that column is not a canonical field.
        """
        values: dict[str, str] = {}
        for field_key, column in mapping.items():
            if field_key in COLUMN_ALIASES:
                continue
            native = clean_text(row.get(column))
            if native is None:
                continue
            translated, matched = configured.translate(field_key, native)
            values[field_key] = translated if matched else native
        return values
