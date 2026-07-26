"""FastAPI entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import providers  # noqa: F401  — importing registers built-in adapters
from app.api import api_router
from app.core.config import get_settings
from app.static import mount_spa

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Import work items, review them, commit them, route them out.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# Last, so the SPA catch-all cannot shadow an API route.
serving_spa = mount_spa(app, settings.static_dir)
