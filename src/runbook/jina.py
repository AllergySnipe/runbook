"""The single place Jina API calls go through — hosted embeddings + reranking.

Provider: **Jina AI** (`https://api.jina.ai/v1`), superseding the local `fastembed`
models of ADR-0002 / ADR-0003 — see `docs/adr/0013`. Moving both models off the
box is what lets the container fit in 512 MB; a new key gets 10M free tokens.

Deliberately thin, mirroring `llm.py`: one client, one retry helper, provider
shapes never leak past this module. **Synchronous on purpose** — the only callers
are `embed.py` / `rag/rerank.py`, reached from `core/loop.py` via
`asyncio.to_thread` (already off the event loop) and from the sync CLI. Blocking
HTTP here is correct; do not "fix" it to async without moving the whole
retrieval stack.
"""

from __future__ import annotations

import time
from typing import Literal

import httpx

from .config import get_settings

_client: httpx.Client | None = None

_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
_MAX_RETRIES = 4
_TIMEOUT_S = 30.0

EmbedTask = Literal["retrieval.query", "retrieval.passage"]


class JinaError(RuntimeError):
    """A Jina API call failed (auth, rate limit after retries, malformed response)."""


def _require_key() -> str:
    key = get_settings().jina_api_key
    if not key or key == "test-key-not-real":
        raise JinaError(
            "JINA_API_KEY is not set. Retrieval needs a Jina key (10M free tokens, "
            "no card): https://jina.ai — add it to .env locally / the Render dashboard."
        )
    return key


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        # trailing slash + relative paths: httpx (RFC 3986) drops the base path
        # for a path that starts with "/", so ".../v1" + "/embeddings" → ".../embeddings".
        _client = httpx.Client(
            base_url=get_settings().jina_base_url.rstrip("/") + "/",
            timeout=_TIMEOUT_S,
        )
    return _client


def _post(path: str, payload: dict, *, what: str) -> dict:
    """POST `payload` to `path`, retrying 429/5xx/connection errors with
    exponential backoff. Raises `JinaError` on give-up or a non-retryable 4xx."""
    headers = {"Authorization": f"Bearer {_require_key()}"}
    last: Exception | str | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = _get_client().post(path, json=payload, headers=headers)
        except httpx.RequestError as exc:  # connection / timeout
            last = exc
        else:
            if resp.status_code == 200:
                return resp.json()
            last = f"{resp.status_code} {resp.text[:200]}"
            if resp.status_code not in _RETRYABLE_STATUS:
                raise JinaError(f"jina {what}: {last}")

        if attempt >= _MAX_RETRIES:
            break
        time.sleep(min(20.0, 1.5 * (2**attempt)))
    raise JinaError(f"jina {what}: giving up after {_MAX_RETRIES + 1} attempts ({last})")


def embed(texts: list[str], *, task: EmbedTask) -> list[list[float]]:
    """Embed `texts` with the configured model. `task` picks the retrieval adapter
    (asymmetric search: queries and passages are encoded differently)."""
    if not texts:
        return []
    data = _post(
        "embeddings",
        {
            "model": get_settings().embedding_model,
            "task": task,
            "input": texts,
        },
        what="embed",
    )
    rows = sorted(data["data"], key=lambda r: r["index"])
    return [r["embedding"] for r in rows]


def rerank(query: str, documents: list[str]) -> list[tuple[int, float]]:
    """Score each document against `query` with the cross-encoder. Returns
    `(original_index, relevance_score)` for every input, best score first."""
    if not documents:
        return []
    data = _post(
        "rerank",
        {
            "model": get_settings().rerank_model,
            "query": query,
            "documents": documents,
            "return_documents": False,
        },
        what="rerank",
    )
    return [(r["index"], float(r["relevance_score"])) for r in data["results"]]
