"""Provider registry.

Adapters self-register at import time. Which of the registered adapters are
*enabled* is a config question (``ENABLED_SOURCES`` / ``ENABLED_DESTINATIONS``),
answered here rather than in any route.
"""

from __future__ import annotations

from typing import TypeVar

from app.core.config import get_settings
from app.providers.base import DestinationProvider, SourceProvider

S = TypeVar("S", bound=SourceProvider)
D = TypeVar("D", bound=DestinationProvider)


class ProviderRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, SourceProvider] = {}
        self._destinations: dict[str, DestinationProvider] = {}

    # -- registration ----------------------------------------------------

    def register_source(self, provider: SourceProvider) -> SourceProvider:
        if provider.id in self._sources:
            raise ValueError(f"duplicate source provider id: {provider.id!r}")
        self._sources[provider.id] = provider
        return provider

    def register_destination(self, provider: DestinationProvider) -> DestinationProvider:
        if provider.id in self._destinations:
            raise ValueError(f"duplicate destination provider id: {provider.id!r}")
        self._destinations[provider.id] = provider
        return provider

    # -- lookup ----------------------------------------------------------

    def source(self, provider_id: str) -> SourceProvider:
        try:
            provider = self._sources[provider_id]
        except KeyError:
            raise KeyError(f"unknown source provider: {provider_id!r}") from None
        if not self.source_enabled(provider_id):
            raise KeyError(f"source provider is disabled: {provider_id!r}")
        return provider

    def destination(self, provider_id: str) -> DestinationProvider:
        try:
            provider = self._destinations[provider_id]
        except KeyError:
            raise KeyError(f"unknown destination provider: {provider_id!r}") from None
        if not self.destination_enabled(provider_id):
            raise KeyError(f"destination provider is disabled: {provider_id!r}")
        return provider

    def source_enabled(self, provider_id: str) -> bool:
        return provider_id in get_settings().enabled_sources

    def destination_enabled(self, provider_id: str) -> bool:
        # "local" is the default sink and is always available; without it a
        # commit would have nowhere to go.
        return provider_id == "local" or provider_id in get_settings().enabled_destinations

    # -- listing ---------------------------------------------------------

    def sources(self, *, enabled_only: bool = True) -> list[SourceProvider]:
        return [
            p
            for p in self._sources.values()
            if not enabled_only or self.source_enabled(p.id)
        ]

    def destinations(self, *, enabled_only: bool = True) -> list[DestinationProvider]:
        return [
            p
            for p in self._destinations.values()
            if not enabled_only or self.destination_enabled(p.id)
        ]

    def reset(self) -> None:
        """Test hook only."""
        self._sources.clear()
        self._destinations.clear()


registry = ProviderRegistry()


def source(cls: type[S]) -> type[S]:
    """Class decorator: instantiate and register a source adapter."""
    registry.register_source(cls())
    return cls


def destination(cls: type[D]) -> type[D]:
    """Class decorator: instantiate and register a destination adapter."""
    registry.register_destination(cls())
    return cls
