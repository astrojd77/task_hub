"""Email source — a saved message file, parsed locally.

Drag a saved `.msg` or `.eml` onto the drop zone (or use the file picker). There
is **no Outlook or Graph connection**: nothing here talks to a mail server, and
the file never leaves the machine except as an upload to this API.

Dragging straight out of the Outlook desktop app is deliberately out of scope —
Outlook exposes a virtual file the browser usually cannot read. The picker
fallback covers that case: save the message first, then pick it.
"""

from __future__ import annotations

import email
import re
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Any

from app.providers.base import ProviderError, RawItem, UploadedFile
from app.providers.registry import source
from app.schemas.task import DraftTask

_HTML_TAGS = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\n{3,}")


@source
class EmailSource:
    id = "email"
    display_name = "Email (.msg / .eml)"

    def config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file": {
                    "type": "file",
                    "accept": ".msg,.eml,message/rfc822,application/vnd.ms-outlook",
                    "required": True,
                }
            },
            "required": ["file"],
            "notes": (
                "Parsed locally — no Outlook or Graph connection. Emails rarely carry a "
                "due date, so expect to fill that in during review."
            ),
        }

    def describe(self, config: dict[str, Any]) -> dict[str, Any]:
        upload = config.get("file")
        return {
            "filename": getattr(upload, "filename", None),
            # One email is one task, so it always gets the single-item modal.
            "review_style": "modal",
        }

    def fetch(self, config: dict[str, Any]) -> list[RawItem]:
        upload = config.get("file")
        if not isinstance(upload, UploadedFile):
            raise ProviderError("no email file was provided")

        name = (upload.filename or "").lower()
        if name.endswith(".msg"):
            parsed = _parse_msg(upload.content, upload.filename)
        elif name.endswith(".eml"):
            parsed = _parse_eml(upload.content, upload.filename)
        else:
            # Extension is the only reliable signal we have — .msg is OLE2 and
            # .eml is RFC822, and browsers give inconsistent MIME types for both.
            raise ProviderError(f"{upload.filename!r} is not a .msg or .eml file")

        return [RawItem(source_ref=parsed["source_ref"], payload=parsed)]

    def to_draft(self, raw: RawItem) -> DraftTask:
        parsed = raw.payload
        warnings: list[str] = list(parsed.get("warnings") or [])

        if not parsed.get("subject"):
            warnings.append("the email has no subject — give this task a title")
        # Emails essentially never carry a due date, so this is a nudge rather
        # than a defect in the parse.
        warnings.append("emails carry no due date, criticality or impact — set them below")

        return DraftTask(
            title=(parsed.get("subject") or "").strip(),
            description=parsed.get("body"),
            source_provider=self.id,
            source_ref=raw.source_ref,
            raw_payload=parsed,
            warnings=warnings,
        )


# -- .eml ----------------------------------------------------------------


def _decode(value: str | None) -> str | None:
    """RFC 2047 encoded-words ("=?utf-8?B?...?=") into real text."""
    if not value:
        return None
    try:
        return str(make_header(decode_header(value))).strip() or None
    except (UnicodeDecodeError, LookupError, ValueError):
        return value.strip() or None


def _parse_eml(content: bytes, filename: str | None) -> dict:
    message: Message = email.message_from_bytes(content)
    warnings: list[str] = []

    body, body_warning = _eml_body(message)
    if body_warning:
        warnings.append(body_warning)

    sent = None
    if message.get("Date"):
        try:
            sent = parsedate_to_datetime(message["Date"]).isoformat()
        except (TypeError, ValueError):
            warnings.append(f"could not read the Date header {message['Date']!r}")

    message_id = (message.get("Message-ID") or "").strip().strip("<>")
    source_ref, ref_warning = _resolve_ref(message_id, content, filename)
    if ref_warning:
        warnings.append(ref_warning)

    attachments = [
        part.get_filename() or "(unnamed)"
        for part in message.walk()
        if part.get_content_disposition() == "attachment"
    ]

    return {
        "source_ref": source_ref,
        "subject": _decode(message.get("Subject")),
        "body": body,
        "from": _decode(message.get("From")),
        "to": _decode(message.get("To")),
        "cc": _decode(message.get("Cc")),
        "sent": sent,
        "message_id": message_id or None,
        "format": "eml",
        "filename": filename,
        # Attachments are out of scope for v1 — recorded, not extracted.
        "attachment_count": len(attachments),
        "attachment_names": attachments,
        "warnings": warnings,
    }


def _eml_body(message: Message) -> tuple[str | None, str | None]:
    """Prefer text/plain; fall back to stripped HTML."""
    plain: str | None = None
    html: str | None = None

    for part in message.walk():
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        try:
            payload = part.get_payload(decode=True)
        except (AssertionError, ValueError):
            continue
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")

        if content_type == "text/plain" and plain is None:
            plain = text
        elif content_type == "text/html" and html is None:
            html = text

    if plain and plain.strip():
        return _tidy(plain), None
    if html and html.strip():
        return _tidy(strip_html(html)), "body taken from the HTML part — formatting is lost"
    return None, "the email had no readable body"


def strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|h[1-6]|li)>", "\n", text)
    text = _HTML_TAGS.sub("", text)
    for entity, char in (
        ("&nbsp;", " "),
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&quot;", '"'),
        ("&#39;", "'"),
    ):
        text = text.replace(entity, char)
    return text


def _tidy(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return _WHITESPACE.sub("\n\n", "\n".join(lines)).strip()


# -- .msg ----------------------------------------------------------------


def _parse_msg(content: bytes, filename: str | None) -> dict:
    try:
        import extract_msg
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise ProviderError(
            "reading .msg files needs the extract-msg package — install the 'email' extra"
        ) from exc

    import io

    warnings: list[str] = []
    try:
        # openMsg rather than Message: it picks the right subclass, so a
        # calendar invite or a contact saved as .msg parses instead of
        # exploding. Attribute access below is guarded accordingly — not every
        # subclass carries every field.
        message = extract_msg.openMsg(io.BytesIO(content))
    except Exception as exc:
        raise ProviderError(f"could not read the .msg file: {exc}") from exc

    try:
        body = getattr(message, "body", None)
        if not (body or "").strip() and getattr(message, "htmlBody", None):
            html = message.htmlBody
            if isinstance(html, bytes):
                html = html.decode("utf-8", errors="replace")
            body = strip_html(html)
            warnings.append("body taken from the HTML part — formatting is lost")

        message_id = (getattr(message, "messageId", None) or "").strip().strip("<>")
        source_ref, ref_warning = _resolve_ref(message_id, content, filename)
        if ref_warning:
            warnings.append(ref_warning)

        sent = getattr(message, "date", None)
        attachments = [
            getattr(a, "longFilename", None) or getattr(a, "shortFilename", None) or "(unnamed)"
            for a in (getattr(message, "attachments", None) or [])
        ]

        def field(name: str) -> str | None:
            return (getattr(message, name, None) or "").strip() or None

        return {
            "source_ref": source_ref,
            "subject": field("subject"),
            "body": _tidy(body) if body else None,
            "from": field("sender"),
            "to": field("to"),
            "cc": field("cc"),
            "sent": (
                sent.isoformat()
                if hasattr(sent, "isoformat")
                else (str(sent) if sent else None)
            ),
            "message_id": message_id or None,
            "format": "msg",
            "filename": filename,
            "attachment_count": len(attachments),
            "attachment_names": attachments,
            "warnings": warnings,
        }
    finally:
        message.close()


# -- idempotency ---------------------------------------------------------


def _resolve_ref(message_id: str, content: bytes, filename: str | None) -> tuple[str, str | None]:
    """Message-ID is the idempotency key; a content hash is the fallback.

    Re-importing the same saved email must update its task rather than create a
    second one. Message-ID is globally unique and stable, which is exactly what
    that needs. Some drafts and some Outlook saves have none, so we fall back to
    hashing the file — and say so, because that key is only as stable as the
    bytes on disk.
    """
    if message_id:
        # Truncated to fit source_ref's column width; Message-IDs are long
        # enough that a 200-char prefix is still unique in practice.
        return message_id[:200], None

    import hashlib

    digest = hashlib.sha256(content).hexdigest()[:32]
    return (
        f"filehash:{digest}",
        "this email has no Message-ID, so it is keyed by file contents — "
        "re-saving it from Outlook may import it a second time",
    )
