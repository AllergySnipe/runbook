"""Deterministic tests — no model calls, no secrets needed."""

from fastapi.testclient import TestClient

from runbook.app import app

client = TestClient(app)


def test_health_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_points_to_health():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["health"] == "/health"
