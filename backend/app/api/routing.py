"""Destination routing: per-task choice, per-project defaults, and pushing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.task import Task
from app.providers.base import ProviderError
from app.schemas.task import TaskOut
from app.services.routing import (
    RoutingError,
    list_routes,
    push_task,
    resolve_destination,
    set_route,
)

router = APIRouter(tags=["routing"])


class RouteOut(BaseModel):
    project: str
    destination: str


class RouteIn(BaseModel):
    project: str
    #: null clears the default, falling the project back to "local".
    destination: str | None = None


class DestinationIn(BaseModel):
    #: null clears the per-task choice, falling back to the project default.
    destination: str | None = None


class PushOut(BaseModel):
    task_id: str
    destination: str
    external_id: str
    url: str | None
    action: str
    task: TaskOut


@router.get("/routes", response_model=list[RouteOut])
def get_routes(db: Session = Depends(get_db)) -> list[RouteOut]:
    return [RouteOut(project=r.project, destination=r.destination) for r in list_routes(db)]


@router.put("/routes", response_model=RouteOut | None)
def put_route(payload: RouteIn, db: Session = Depends(get_db)) -> RouteOut | None:
    try:
        route = set_route(db, payload.project, payload.destination)
    except RoutingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RouteOut(project=route.project, destination=route.destination) if route else None


@router.put("/tasks/{task_id}/destination", response_model=TaskOut)
def set_task_destination(
    task_id: str, payload: DestinationIn, db: Session = Depends(get_db)
) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    if payload.destination is not None:
        from app.providers.registry import registry

        try:
            registry.destination(payload.destination)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    task.destination = payload.destination
    db.commit()
    db.refresh(task)
    return task


@router.get("/tasks/{task_id}/destination")
def get_task_destination(task_id: str, db: Session = Depends(get_db)) -> dict:
    """What would happen if this task were pushed right now, and why."""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    resolved = resolve_destination(db, task)
    if task.destination:
        reason = "set on the task"
    elif resolved != "local":
        reason = f"default for project {task.project!r}"
    else:
        reason = "fallback"

    return {
        "explicit": task.destination,
        "resolved": resolved,
        "reason": reason,
        "external_refs": task.external_refs or {},
    }


@router.post("/tasks/{task_id}/push", response_model=PushOut)
def push(task_id: str, db: Session = Depends(get_db)) -> PushOut:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    try:
        outcome = push_task(db, task)
    except RoutingError as exc:
        # The loop-back guardrail lands here — a 409 because the request is
        # coherent but conflicts with where this task came from.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PushOut(
        task_id=outcome.task_id,
        destination=outcome.destination,
        external_id=outcome.external_id,
        url=outcome.url,
        action=outcome.action,
        task=TaskOut.model_validate(task),
    )
