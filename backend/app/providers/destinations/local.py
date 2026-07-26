"""The local destination — the default sink.

A committed task already lives in the local database, so pushing to "local" is
a no-op that simply reports the task's own id as its external reference. It
exists so that routing has a real, always-available default and so the routing
layer never needs a "no destination" special case.
"""

from __future__ import annotations

from typing import Any

from app.providers.base import Capabilities, ExternalRef
from app.providers.registry import destination
from app.schemas.task import TaskOut


@destination
class LocalDestination:
    id = "local"
    display_name = "Local (Task Hub)"
    capabilities = Capabilities(create=True, update=True, close=True)

    def config_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def push(self, task: TaskOut) -> ExternalRef:
        return ExternalRef(provider=self.id, external_id=task.id)

    def update(self, task: TaskOut, ref: ExternalRef) -> None:
        return None

    def close(self, task: TaskOut, ref: ExternalRef) -> None:
        return None
