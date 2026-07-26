"""Provider adapters.

Importing this package registers every built-in adapter as a side effect, so
``app.main`` only has to import ``app.providers``.

Adding a platform = write one adapter module, import it here. Core never
changes.
"""

# Destinations
from app.providers.destinations import local as _local  # noqa: F401
from app.providers.registry import registry

__all__ = ["registry"]
