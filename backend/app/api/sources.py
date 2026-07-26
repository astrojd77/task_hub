"""POST /api/sources/{id}/drafts — parse, never persist.

One uniform entry point for every inbound adapter. The request is always
multipart so that file-based sources (csv, email) and config-only sources
(jira) share a shape: an optional ``file`` part plus a JSON ``config`` part.

Nothing here writes to the task store. The response is a batch of drafts for
the user to review; committing them is a separate, explicit call.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.providers import registry
from app.providers.base import ProviderError, UploadedFile
from app.schemas.task import DraftBatch
from app.services.drafts import build_batch

router = APIRouter(prefix="/sources", tags=["sources"])

#: Guards against a stray multi-hundred-MB upload turning into memory pressure.
MAX_UPLOAD_BYTES = 16 * 1024 * 1024


@router.post("/{source_id}/drafts", response_model=DraftBatch)
async def build_drafts(
    source_id: str,
    file: UploadFile | None = File(default=None),
    config: str = Form(default="{}"),
    db: Session = Depends(get_db),
) -> DraftBatch:
    try:
        provider = registry.source(source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        parsed_config: Any = json.loads(config or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"config is not valid JSON: {exc}") from exc
    if not isinstance(parsed_config, dict):
        raise HTTPException(status_code=422, detail="config must be a JSON object")

    if file is not None:
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
            )
        parsed_config["file"] = UploadedFile(
            filename=file.filename or "upload", content=content
        )

    try:
        return build_batch(db, provider, parsed_config)
    except ProviderError as exc:
        # Adapter-level problems are the user's to fix (bad file, bad mapping),
        # so the message goes back verbatim rather than as a 500.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
