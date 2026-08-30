"""Deterministic tests — no model calls, no secrets needed."""

from fastapi.testclient import TestClient

from runbook.app import app

client = TestClient(app)


def test_health_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_serves_something():
    """Dev (no web/dist): a JSON pointer at the API. Prod (web/dist built): the
    SPA's index.html. Either way `/` must be 200 and not shadow the API."""
    response = client.get("/")
    assert response.status_code == 200
