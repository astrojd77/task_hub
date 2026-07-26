from fastapi import APIRouter

from app.api import commit, meta, tasks

api_router = APIRouter(prefix="/api")
api_router.include_router(meta.router)
api_router.include_router(tasks.router)
api_router.include_router(commit.router)

__all__ = ["api_router"]
