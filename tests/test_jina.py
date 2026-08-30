"""Jina client tests — deterministic, no network (httpx MockTransport).

Covers the request shape (model, task, auth header), response parsing / ordering,
the missing-key guard, and retry-then-give-up on 5xx.
"""

import json

import httpx
import pytest

from runbook import jina


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Fresh client + settings each test; real key by default; no real sleeps."""
    monkeypatch.setenv("JINA_API_KEY", "real-key")
    monkeypatch.setattr(jina.time, "sleep", lambda _s: None)
    jina._client = None
    jina.get_settings.cache_clear()
    yield
    jina._client = None
    jina.get_settings.cache_clear()


def _install(handler):
    # same base_url join as _get_client (trailing slash + relative paths)
    jina._client = httpx.Client(
        base_url="https://api.jina.ai/v1/", transport=httpx.MockTransport(handler)
    )


def test_embed_sends_model_task_key_and_parses_by_index():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["json"] = json.loads(request.content)
        return httpx.Response(  # out of order — we must sort by index
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            },
        )

    _install(handler)
    out = jina.embed(["alpha", "beta"], task="retrieval.passage")

    assert out == [[0.1, 0.2], [0.3, 0.4]]
    assert seen["url"] == "https://api.jina.ai/v1/embeddings"  # base path kept
    assert seen["auth"] == "Bearer real-key"
    assert seen["json"]["task"] == "retrieval.passage"
    assert seen["json"]["model"] == "jina-embeddings-v5-text-small"
    assert seen["json"]["input"] == ["alpha", "beta"]


def test_rerank_returns_index_score_pairs():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 2, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.4},
                ]
            },
        )

    _install(handler)
    assert jina.rerank("q", ["a", "b", "c"]) == [(2, 0.9), (0, 0.4)]


def test_missing_key_raises_clear_error(monkeypatch):
    monkeypatch.setenv("JINA_API_KEY", "test-key-not-real")
    jina.get_settings.cache_clear()
    with pytest.raises(jina.JinaError, match="JINA_API_KEY is not set"):
        jina.embed(["x"], task="retrieval.query")


def test_empty_input_short_circuits():
    assert jina.embed([], task="retrieval.query") == []
    assert jina.rerank("q", []) == []


def test_retryable_status_eventually_raises(monkeypatch):
    monkeypatch.setattr(jina, "_MAX_RETRIES", 2)
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="upstream unavailable")

    _install(handler)
    with pytest.raises(jina.JinaError, match="giving up after 3 attempts"):
        jina.rerank("q", ["a"])
    assert calls["n"] == 3


def test_non_retryable_4xx_raises_immediately():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(422, text="bad model")

    _install(handler)
    with pytest.raises(jina.JinaError, match="422"):
        jina.embed(["x"], task="retrieval.query")
    assert calls["n"] == 1
