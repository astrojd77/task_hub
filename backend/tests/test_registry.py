"""The provider abstraction is the product — guard its edges."""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.providers import registry
from app.providers.base import Capabilities, DestinationProvider, ExternalRef, SourceProvider
from app.providers.registry import ProviderRegistry
from app.schemas.task import TaskOut


def test_local_destination_is_registered_and_always_enabled():
    local = registry.destination("local")
    assert local.id == "local"
    assert local.capabilities.create


def test_local_stays_available_even_if_config_omits_it(monkeypatch):
    """Commit must always have somewhere to go."""
    settings = get_settings()
    monkeypatch.setattr(settings, "enabled_destinations", [], raising=False)
    assert registry.destination_enabled("local")


def test_disabled_destination_is_not_resolvable(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "enabled_destinations", ["local"], raising=False)

    reg = ProviderRegistry()

    class Fake:
        id = "asana"
        display_name = "Asana"
        capabilities = Capabilities(create=True)

        def config_schema(self):
            return {}

        def push(self, task):
            return ExternalRef(provider=self.id, external_id="1")

        def update(self, task, ref):
            return None

        def close(self, task, ref):
            return None

    reg.register_destination(Fake())
    assert reg.destinations() == []
    with pytest.raises(KeyError):
        reg.destination("asana")


def test_duplicate_registration_is_rejected():
    reg = ProviderRegistry()

    class Fake:
        id = "dup"
        display_name = "Dup"
        capabilities = Capabilities()

        def config_schema(self):
            return {}

        def push(self, task): ...

        def update(self, task, ref): ...

        def close(self, task, ref): ...

    reg.register_destination(Fake())
    with pytest.raises(ValueError, match="duplicate"):
        reg.register_destination(Fake())


def test_unknown_provider_raises_keyerror():
    with pytest.raises(KeyError):
        registry.source("carrier-pigeon")


def test_registered_adapters_satisfy_their_protocol():
    for provider in registry.destinations(enabled_only=False):
        assert isinstance(provider, DestinationProvider), provider.id
    for provider in registry.sources(enabled_only=False):
        assert isinstance(provider, SourceProvider), provider.id


def test_local_push_reports_the_task_id(db):
    from datetime import datetime

    task = TaskOut(
        id="abc-123",
        title="t",
        description=None,
        status="todo",
        priority="medium",
        criticality=None,
        impact_size=None,
        due_date=None,
        assignee=None,
        project=None,
        labels=[],
        custom_fields={},
        source_provider="csv",
        source_ref="r1",
        external_refs={},
        destination="local",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    ref = registry.destination("local").push(task)
    assert ref == ExternalRef(provider="local", external_id="abc-123")
