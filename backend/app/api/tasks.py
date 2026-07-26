"""Task list / detail / edit."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.task import Task
from app.schemas.task import TaskOut
from app.services.filters import TaskFilters, task_filters

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
def list_tasks(
    filters: TaskFilters = Depends(task_filters),
    limit: int = Query(default=500, le=2000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[Task]:
    stmt = (
        filters.apply(select(Task))
        # id is the tiebreaker so a bulk commit (many rows, identical
        # timestamps) still paginates deterministically.
        .order_by(Task.created_at.desc(), Task.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars())


@router.get("/facets")
def facets(db: Session = Depends(get_db)) -> dict[str, list[str]]:
    """Distinct values behind the filter dropdowns."""

    def distinct(column) -> list[str]:
        rows = db.execute(select(column).where(column.is_not(None)).distinct()).scalars()
        return sorted({r for r in rows if r})

    return {
        "source": distinct(Task.source_provider),
        "destination": distinct(Task.destination),
        "project": distinct(Task.project),
        "assignee": distinct(Task.assignee),
    }


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(get_db)) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str, db: Session = Depends(get_db)) -> None:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    db.delete(task)
    db.commit()
