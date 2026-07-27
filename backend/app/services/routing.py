"""Routing: deciding where a committed task goes, and sending it there.

The guardrail in ``check_push_allowed`` is the important part of this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.routing import ProjectRoute
from app.models.task import Task, utcnow
from app.providers.base import DestinationProvider, ProviderError
from app.providers.registry import registry
from app.schemas.task import TaskOut

DEFAULT_DESTINATION = "local"


class RoutingError(ProviderError):
    """The task must not go to this destination."""


def resolve_destination(db: Session, task: Task) -> str:
    """Most specific wins: task, then project default, then local."""
    if task.destination:
        return task.destination
    if task.project:
        route = db.execute(
            select(ProjectRoute).where(ProjectRoute.project == task.project)
        ).scalar_one_or_none()
        if route is not None:
            return route.destination
    return DEFAULT_DESTINATION


def check_push_allowed(task: Task, destination_id: str) -> None:
    """Guardrail against a task looping back into the system it came from.

    A task imported *from* Jira must not be pushed *to* Jira as a brand new
    issue — that silently duplicates the original. Updating the issue it came
    from is fine and is what the update path does, so the block is specifically
    on creating a second one.

    Generalised beyond Jira on purpose: the same trap exists for every adapter
    that is both a source and a destination.
    """
    if task.source_provider != destination_id:
        return

    already_linked = destination_id in (task.external_refs or {})
    if already_linked:
        return

    raise RoutingError(
        f"this task came from {destination_id} ({task.source_ref}) — pushing it back to "
        f"{destination_id} would create a duplicate issue. Update the original instead."
    )


@dataclass
class PushOutcome:
    task_id: str
    destination: str
    external_id: str
    url: str | None
    action: str  # "created" | "updated"


def push_task(db: Session, task: Task, destination_id: str | None = None) -> PushOutcome:
    """Send a committed task to its destination and record where it landed."""
    target = destination_id or resolve_destination(db, task)

    try:
        provider: DestinationProvider = registry.destination(target)
    except KeyError as exc:
        raise RoutingError(str(exc)) from exc

    existing_id = (task.external_refs or {}).get(target)

    if existing_id:
        if not provider.capabilities.update:
            raise RoutingError(f"{target} cannot update existing items")
        from app.providers.base import ExternalRef

        ref = ExternalRef(provider=target, external_id=existing_id)
        provider.update(TaskOut.model_validate(task), ref)
        action = "updated"
    else:
        check_push_allowed(task, target)
        if not provider.capabilities.create:
            raise RoutingError(f"{target} cannot create new items")
        ref = provider.push(TaskOut.model_validate(task))
        action = "created"

    # Reassign rather than mutate: PortableJSON tracks changes by identity, so
    # an in-place dict update would not be flushed.
    task.external_refs = {**(task.external_refs or {}), target: ref.external_id}
    task.destination = target
    task.updated_at = utcnow()
    db.commit()
    db.refresh(task)

    return PushOutcome(
        task_id=task.id,
        destination=target,
        external_id=ref.external_id,
        url=ref.url,
        action=action,
    )


# -- project defaults ----------------------------------------------------


def list_routes(db: Session) -> list[ProjectRoute]:
    return list(db.execute(select(ProjectRoute).order_by(ProjectRoute.project)).scalars())


def set_route(db: Session, project: str, destination: str | None) -> ProjectRoute | None:
    """Set or clear a project's default destination."""
    existing = db.execute(
        select(ProjectRoute).where(ProjectRoute.project == project)
    ).scalar_one_or_none()

    if destination is None:
        if existing is not None:
            db.delete(existing)
            db.commit()
        return None

    try:
        registry.destination(destination)
    except KeyError as exc:
        raise RoutingError(str(exc)) from exc

    if existing is None:
        existing = ProjectRoute(project=project, destination=destination)
        db.add(existing)
    else:
        existing.destination = destination
        existing.updated_at = utcnow()

    db.commit()
    db.refresh(existing)
    return existing
