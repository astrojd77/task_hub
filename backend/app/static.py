"""Serving the built single-page app alongside the API.

Only active when the static directory exists — that is true in the container
image and false in local dev, where Vite serves the frontend itself.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

#: Paths the SPA fallback must never swallow.
_API_PREFIXES = ("api", "docs", "redoc", "openapi.json")


def mount_spa(app: FastAPI, directory: str) -> bool:
    """Serve ``directory`` as the SPA. Returns whether it was mounted.

    Must be called *after* the API routes are registered: the catch-all below
    matches any path, so it has to be last in the routing table.
    """
    root = Path(directory).resolve()
    index = root / "index.html"
    if not index.is_file():
        return False

    assets = root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.split("/", 1)[0] in _API_PREFIXES:
            # Let a genuine unmatched API path 404 as itself rather than
            # handing the caller an HTML page.
            raise HTTPException(status_code=404, detail="not found")

        candidate = (root / path).resolve()
        # Serve a real file when one exists, but never escape the static root.
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)

        # Everything else is a client-side route.
        return FileResponse(index)

    return True
