"""FastAPI entrypoint.

Two faces of one core (SPEC): the `runbook` CLI drives `core/` directly; this
app exposes the same loop over HTTP + SSE (`web_api.py`) and serves the built
React dashboard (`web/dist/`) as static files.

Local:  uv run uvicorn runbook.app:app --reload --port 8000
        (frontend dev server: cd web && npm run dev  — proxies /api to :8000)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import web_api

_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await web_api.shutdown()  # cancel any in-flight incident tasks


app = FastAPI(title="Runbook", version="0.1.0", lifespan=lifespan)

app.include_router(web_api.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check — does no real work. Render's health check + the keep-warm ping."""
    return {"status": "ok"}


if _DIST.is_dir():
    # Prod: serve the built SPA. Mounted last so it can't shadow /api or /health.
    # `html=True` serves index.html for `/`; the catch-all below covers SPA deep
    # links (a refresh on /incidents/run_abc has no matching file).
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/")
    def _index() -> FileResponse:
        return FileResponse(_DIST / "index.html")

    @app.get("/{path:path}")
    def _spa(path: str) -> FileResponse:
        candidate = _DIST / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")

else:

    @app.get("/")
    def _root_dev() -> dict[str, str]:
        """Dev only (no web/dist built): point at the API + health."""
        return {"service": "runbook", "docs": "/docs", "health": "/health", "api": "/api"}
