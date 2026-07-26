"""POST /api/commit — the only way a task enters the store."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.task import CommitRequest, CommitResult
from app.services.commit import commit_drafts

router = APIRouter(tags=["commit"])


@router.post("/commit", response_model=CommitResult)
def commit(payload: CommitRequest, db: Session = Depends(get_db)) -> CommitResult:
    """Validate reviewed drafts and upsert them.

    FastAPI rejects the request outright if a draft fails schema validation
    (blank title, bad enum value). Softer problems — a missing due date, an
    unset criticality — come back as warnings alongside the committed tasks.
    """
    return commit_drafts(db, payload.drafts, payload.default_destination)
