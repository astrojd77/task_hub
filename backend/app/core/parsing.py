"""Shared value parsing.

Format-level helpers only. Anything that translates a *platform's* vocabulary
into the canonical enums belongs in that platform's adapter, not here.
"""

from __future__ import annotations

from datetime import date, datetime

#: Tried in order. ISO first; everything after it is a guess, and a guess gets
#: reported back to the user as a warning rather than applied silently.
_DATE_FORMATS: tuple[tuple[str, str], ...] = (
    ("%Y-%m-%d", "ISO"),
    ("%Y/%m/%d", "Y/M/D"),
    ("%m/%d/%Y", "US month-first"),
    ("%m/%d/%y", "US month-first"),
    ("%d-%b-%Y", "D-Mon-Y"),
    ("%d %b %Y", "D Mon Y"),
    ("%b %d, %Y", "Mon D, Y"),
    ("%d.%m.%Y", "D.M.Y"),
)


def parse_date(value: object) -> tuple[date | None, str | None]:
    """Best-effort date parse.

    Returns ``(date, warning)``. The warning is non-empty when the value could
    not be parsed, or when it parsed only under an ambiguous format — e.g.
    ``03/04/2026`` is read month-first, but it is genuinely ambiguous and the
    user deserves to be told so in the review screen.
    """
    if value is None:
        return None, None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value, None
    if isinstance(value, datetime):
        return value.date(), None

    text = str(value).strip()
    if not text:
        return None, None

    # Trailing time component, e.g. "2026-08-01 17:00" or an ISO timestamp.
    head = text.replace("T", " ").split(" ", 1)[0]

    for fmt, label in _DATE_FORMATS:
        try:
            # A due date is a calendar date, not an instant — there is no zone
            # to attach, and .date() discards the parser's midnight anyway.
            parsed = datetime.strptime(head, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
        if label.startswith("US month-first") and _is_ambiguous_slash_date(head):
            return parsed, (
                f"read {text!r} as {parsed.isoformat()} (month-first); "
                "day-first would give a different date"
            )
        return parsed, None

    return None, f"could not read {text!r} as a date — set it manually"


def _is_ambiguous_slash_date(text: str) -> bool:
    """True when both halves are <= 12, so month-first vs day-first differ."""
    parts = text.split("/")
    if len(parts) != 3:
        return False
    try:
        first, second = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return first <= 12 and second <= 12 and first != second


def split_labels(value: object) -> list[str]:
    """Split a labels cell on commas, semicolons or pipes."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    for sep in (",", ";", "|"):
        if sep in text:
            return [part.strip() for part in text.split(sep) if part.strip()]
    return [text]


def clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
