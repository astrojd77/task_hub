"""Provider adapters.

Importing this package registers every built-in adapter as a side effect, so
``app.main`` only has to import ``app.providers``.

Adding a platform = write one adapter module, import it here. Core never
changes.
"""

# Destinations
from app.providers.destinations import jira as _jira_dest  # noqa: F401
from app.providers.destinations import local as _local  # noqa: F401
from app.providers.registry import registry

# Sources
from app.providers.sources import csv_source as _csv  # noqa: F401
from app.providers.sources import email_source as _email  # noqa: F401
from app.providers.sources import jira_source as _jira_source  # noqa: F401

__all__ = ["registry"]
