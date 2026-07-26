"""Health, enum catalog, and provider discovery.

The frontend builds its source pickers, destination pickers and enum dropdowns
from these responses, so a newly registered adapter shows up in the UI without
any frontend change.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.enums import ENUM_CATALOG
from app.providers import registry

router = APIRouter(tags=["meta"])


class SourceInfo(BaseModel):
    id: str
    display_name: str
    config_schema: dict


class DestinationInfo(BaseModel):
    id: str
    display_name: str
    capabilities: dict[str, bool]
    config_schema: dict


class ProvidersOut(BaseModel):
    sources: list[SourceInfo]
    destinations: list[DestinationInfo]


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        # Dialect only — never echo credentials.
        "db_dialect": settings.database_url.split("://", 1)[0],
    }


@router.get("/enums")
def enums() -> dict[str, list[str]]:
    return ENUM_CATALOG


@router.get("/providers", response_model=ProvidersOut)
def providers() -> ProvidersOut:
    return ProvidersOut(
        sources=[
            SourceInfo(
                id=p.id,
                display_name=p.display_name,
                config_schema=p.config_schema(),
            )
            for p in registry.sources()
        ],
        destinations=[
            DestinationInfo(
                id=p.id,
                display_name=p.display_name,
                capabilities=p.capabilities.as_dict(),
                config_schema=p.config_schema(),
            )
            for p in registry.destinations()
        ],
    )
