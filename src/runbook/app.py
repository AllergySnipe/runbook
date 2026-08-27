"""FastAPI entrypoint.

Week 0: a liveness check and one live model call, to prove the whole chain
(image -> container -> $PORT -> prod key -> model API) before real logic lands.

Local:  uv run uvicorn runbook.app:app --reload --port 8000
"""

from fastapi import FastAPI
from pydantic import BaseModel

from .config import get_settings
from .llm import complete

app = FastAPI(title="Runbook", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check — does no real work. Render's health check and the keep-warm ping."""
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "runbook", "docs": "/docs", "health": "/health"}


class DemoRequest(BaseModel):
    prompt: str


class DemoResponse(BaseModel):
    reply: str
    model: str


@app.post("/api/demo", response_model=DemoResponse)
async def demo(req: DemoRequest) -> DemoResponse:
    """Smoke test for a live model call. Deleted once the real endpoints land."""
    model = get_settings().triage_model
    reply = await complete(req.prompt, model=model, max_tokens=256)
    return DemoResponse(reply=reply, model=model)
