"""Email source: local parsing, Message-ID idempotency, review-ready drafts."""

from __future__ import annotations

import pytest

from app.providers.base import ProviderError, UploadedFile
from app.providers.sources.email_source import EmailSource, strip_html

EML = """\
Message-ID: <abc123@mail.example.com>
Date: Fri, 24 Jul 2026 09:15:00 +0100
From: Ana Ruiz <ana@example.com>
To: Jared <jared@example.com>
Cc: Ops <ops@example.com>
Subject: Cert renewal needs sign-off
Content-Type: text/plain; charset="utf-8"

The prod signing cert expires on the 1st.

Can you approve the renewal?
"""

MULTIPART = """\
Message-ID: <multi@mail.example.com>
Subject: Quarterly review
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="BOUND"

--BOUND
Content-Type: text/plain; charset="utf-8"

Plain text version.

--BOUND
Content-Type: text/html; charset="utf-8"

<html><body><p>HTML version.</p></body></html>

--BOUND--
"""

HTML_ONLY = """\
Message-ID: <htmlonly@mail.example.com>
Subject: Styled note
MIME-Version: 1.0
Content-Type: text/html; charset="utf-8"

<html><body><style>p{color:red}</style><p>First para.</p><p>Second &amp; last.</p></body></html>
"""


def upload(text: str, name: str = "note.eml") -> UploadedFile:
    return UploadedFile(filename=name, content=text.encode("utf-8"))


def draft_for(text: str, name: str = "note.eml"):
    source = EmailSource()
    items = source.fetch({"file": upload(text, name)})
    return source.to_draft(items[0])


# -- parsing -------------------------------------------------------------


def test_eml_maps_subject_to_title_and_body_to_description():
    draft = draft_for(EML)

    assert draft.title == "Cert renewal needs sign-off"
    assert "expires on the 1st" in draft.description
    assert "approve the renewal" in draft.description


def test_sender_and_dates_go_to_raw_payload_not_the_task():
    draft = draft_for(EML)

    assert draft.raw_payload["from"] == "Ana Ruiz <ana@example.com>"
    assert draft.raw_payload["to"] == "Jared <jared@example.com>"
    assert draft.raw_payload["cc"] == "Ops <ops@example.com>"
    assert draft.raw_payload["sent"].startswith("2026-07-24T09:15:00")


def test_plain_text_wins_over_html_in_a_multipart_email():
    draft = draft_for(MULTIPART)
    assert draft.description == "Plain text version."


def test_html_only_email_falls_back_to_stripped_html_and_says_so():
    draft = draft_for(HTML_ONLY)

    assert "First para." in draft.description
    assert "Second & last." in draft.description
    assert "<p>" not in draft.description
    assert "color:red" not in draft.description  # style block dropped entirely
    assert any("HTML part" in w for w in draft.warnings)


def test_encoded_subject_is_decoded():
    raw = "Message-ID: <e@x>\nSubject: =?utf-8?B?Q2Fmw6kgcGxhbm5pbmc=?=\n\nbody\n"
    assert draft_for(raw).title == "Café planning"


def test_email_with_no_body_warns():
    draft = draft_for("Message-ID: <e@x>\nSubject: Just a subject\n\n")
    assert any("no readable body" in w for w in draft.warnings)


def test_email_with_no_subject_is_flagged_for_review_not_dropped():
    draft = draft_for("Message-ID: <e@x>\n\nJust a body\n")

    assert draft.title == ""
    assert any("no subject" in w for w in draft.warnings)


def test_attachments_are_counted_not_extracted():
    raw = (
        "Message-ID: <att@x>\nSubject: With attachment\n"
        'MIME-Version: 1.0\nContent-Type: multipart/mixed; boundary="B"\n\n'
        "--B\nContent-Type: text/plain\n\nSee attached.\n\n"
        "--B\nContent-Type: application/pdf\n"
        'Content-Disposition: attachment; filename="report.pdf"\n\n'
        "%PDF-1.4\n--B--\n"
    )
    draft = draft_for(raw)

    assert draft.raw_payload["attachment_count"] == 1
    assert draft.raw_payload["attachment_names"] == ["report.pdf"]


# -- review expectations -------------------------------------------------


def test_the_review_fields_are_left_blank_for_the_user():
    """An email carries none of this — the modal exists to collect it."""
    draft = draft_for(EML)

    assert draft.due_date is None
    assert draft.criticality is None
    assert draft.impact_size is None
    assert draft.project is None
    assert any("set them below" in w for w in draft.warnings)


def test_email_is_always_reviewed_as_a_modal():
    assert EmailSource().describe({"file": upload(EML)})["review_style"] == "modal"


# -- idempotency ---------------------------------------------------------


def test_message_id_is_the_idempotency_key():
    assert draft_for(EML).source_ref == "abc123@mail.example.com"


def test_the_same_email_twice_yields_the_same_ref():
    assert draft_for(EML).source_ref == draft_for(EML).source_ref


def test_missing_message_id_falls_back_to_a_content_hash_and_warns():
    draft = draft_for("Subject: No id here\n\nbody\n")

    assert draft.source_ref.startswith("filehash:")
    assert any("no Message-ID" in w for w in draft.warnings)


def test_different_emails_get_different_refs():
    a = draft_for(EML)
    b = draft_for(MULTIPART)
    assert a.source_ref != b.source_ref


# -- file handling -------------------------------------------------------


def test_unsupported_extension_is_rejected():
    with pytest.raises(ProviderError, match=r"not a \.msg or \.eml"):
        EmailSource().fetch({"file": upload(EML, "notes.txt")})


def test_missing_file_is_rejected():
    with pytest.raises(ProviderError, match="no email file"):
        EmailSource().fetch({})


def test_corrupt_msg_is_a_provider_error_not_a_crash():
    with pytest.raises(ProviderError, match=r"could not read the \.msg"):
        EmailSource().fetch({"file": UploadedFile(filename="x.msg", content=b"not really OLE2")})


def test_strip_html_drops_scripts_and_keeps_line_structure():
    html = "<div>One</div><script>evil()</script><div>Two</div>"
    text = strip_html(html)

    assert "evil" not in text
    assert "One" in text and "Two" in text
