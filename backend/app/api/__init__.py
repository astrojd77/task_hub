from fastapi import APIRouter

from app.api import commit, config, meta, routing, sources, tasks, watch

api_router = APIRouter(prefix="/api")
api_router.include_router(meta.router)
api_router.include_router(config.router)
api_router.include_router(tasks.router)
api_router.include_router(sources.router)
api_router.include_router(commit.router)
api_router.include_router(watch.router)
api_router.include_router(routing.router)

__all__ = ["api_router"]
