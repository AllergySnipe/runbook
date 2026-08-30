"""The dashboard's HTTP + SSE surface (`web_api.py`).

Deterministic: `diagnose` is replaced with a fake that emits a scripted event
sequence, and the `store` functions are faked — no model calls, no database.
What's under test is the *plumbing*: the background task, the in-memory
registry, SSE replay + live streaming, and the approve/reject wiring.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from runbook import web_api
from runbook.app import app
from runbook.core import events as ev
from runbook.core.store import ApprovalRecord, RunRecord

client = TestClient(app)


# --- fakes -----------------------------------------------------------------


SCRIPT = [
    ev.event(ev.TRIAGE_START),
    ev.event(ev.TRIAGE_DONE, category="known-runbook", proceed=True),
    ev.event(ev.RETRIEVE_DONE, docs=["corpus/synthetic/db-pool.md"]),
    ev.event(ev.TOOL_CALL, name="query_metrics", input={"metric": "db_pool"}, is_error=False),
    ev.event(ev.SYNTHESIS_DONE, confidence="high", failure_mode="db-pool", n_steps=2),
    ev.event(ev.DISPOSITION, disposition="needs-approval"),
]


async def fake_diagnose(alert, scenario, *, k=4, on_event=None, use_cache=False):
    emit = on_event or (lambda e: None)
    for e in SCRIPT:
        emit(e)
    return _SENTINEL_RESULT


_SENTINEL_RESULT = object()


def fake_run(run_id: str, *, status: str = "awaiting-approval", approvals: list | None = None):
    if approvals is None:
        approvals = [
            ApprovalRecord(
                id=1,
                step_index=0,
                action="restart the connection pool",
                runbook_quote="restart the connection pool",
                classifier_reason="verb 'restart'",
                state="pending",
                resolved_by=None,
                resolved_at=None,
                note=None,
            )
        ]
    return RunRecord(
        id=run_id,
        alert="alert text",
        scenario="db-connection-pool-exhaustion",
        triage_category="known-runbook",
        triage_rationale="matches a runbook",
        triage_confidence="high",
        disposition="needs-approval",
        status=status,
        diagnosis=None,
        retrieved=[],
        tool_calls=[],
        guardrail=None,
        usage={},
        iterations=3,
        hit_max_iters=False,
        elapsed_s=12.0,
        created_at=datetime.now(UTC),
        resolved_at=None,
        approvals=approvals,
    )


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    web_api._RUNS.clear()
    monkeypatch.setattr(web_api, "diagnose", fake_diagnose)
    monkeypatch.setattr(web_api, "record_run", lambda result, *, run_id: fake_run(run_id))
    monkeypatch.setattr(web_api, "list_runs", lambda **kw: [])
    yield
    web_api._RUNS.clear()


def _drain_sse(run_id: str) -> list[str]:
    """Open the SSE stream and collect event names until it closes."""
    names: list[str] = []
    with client.stream("GET", f"/api/incidents/{run_id}/events") as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("event:"):
                names.append(line.split(":", 1)[1].strip())
    return names


# --- tests ---------------------------------------------------------------


def test_start_returns_id_immediately():
    resp = client.post("/api/incidents", json={"scenario": "db-connection-pool-exhaustion"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["id"].startswith("run_")
    assert body["status"] == "running"


def test_start_unknown_scenario_404():
    resp = client.post("/api/incidents", json={"scenario": "no-such-scenario"})
    assert resp.status_code == 404


def test_sse_streams_the_scripted_events_then_finishes():
    run_id = client.post(
        "/api/incidents", json={"scenario": "db-connection-pool-exhaustion"}
    ).json()["id"]
    names = _drain_sse(run_id)
    # every scripted event, in order, plus a terminal 'finished'
    assert names[: len(SCRIPT)] == [e["type"] for e in SCRIPT]
    assert names[-1] == ev.FINISHED


def test_sse_unknown_id_404():
    with client.stream("GET", "/api/incidents/run_missing/events") as r:
        assert r.status_code == 404


def test_get_incident_after_finish_returns_persisted_record(monkeypatch):
    run_id = client.post(
        "/api/incidents", json={"scenario": "db-connection-pool-exhaustion"}
    ).json()["id"]
    _drain_sse(run_id)  # let the background task finish + persist

    monkeypatch.setattr(web_api, "get_run", fake_run)
    resp = client.get(f"/api/incidents/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "awaiting-approval"


def test_list_merges_in_flight_runs():
    web_api._RUNS["run_live"] = web_api.IncidentRun(
        id="run_live",
        alert="a",
        scenario="redis-eviction-idempotency",
        created_at=datetime.now(UTC),
    )
    rows = client.get("/api/incidents").json()
    assert rows[0]["id"] == "run_live"
    assert rows[0]["status"] == "running"


def test_reject_requires_a_note(monkeypatch):
    monkeypatch.setattr(web_api, "get_run", fake_run)
    resp = client.post("/api/incidents/run_x/reject", json={"by": "ritvik"})
    assert resp.status_code == 422


def test_approve_wires_through_to_resolve_approvals(monkeypatch):
    seen = {}

    def fake_resolve(run_id, *, decision, step, by, note):
        seen.update(run_id=run_id, decision=decision, step=step, by=by)
        return fake_run(run_id, status="resolved", approvals=[])

    monkeypatch.setattr(web_api, "get_run", fake_run)
    monkeypatch.setattr(web_api, "resolve_approvals", fake_resolve)

    resp = client.post("/api/incidents/run_x/approve", json={"by": "ritvik", "step": 0})
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"
    assert seen == {"run_id": "run_x", "decision": "approve", "step": 0, "by": "ritvik"}


def test_approve_on_terminal_run_409(monkeypatch):
    monkeypatch.setattr(web_api, "get_run", lambda rid: fake_run(rid, status="resolved"))
    resp = client.post("/api/incidents/run_x/approve", json={"by": "ritvik"})
    assert resp.status_code == 409


def test_scenarios_endpoint_lists_the_sim_fixtures():
    resp = client.get("/api/scenarios")
    assert resp.status_code == 200
    rows = resp.json()
    names = [s["name"] for s in rows]
    assert "db-connection-pool-exhaustion" in names
    # enriched fields the launcher needs
    sc = next(s for s in rows if s["name"] == "bad-migration-table-lock")
    assert sc["severity"] == "SEV1"
    assert sc["expected_runbook"] and sc["metrics"]


def test_decisions_endpoint_indexes_the_adrs():
    resp = client.get("/api/decisions")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) >= 8
    first = rows[0]
    assert first["number"] == 1
    assert first["status"] and first["title"] and first["context"]
    assert rows == sorted(rows, key=lambda r: r["number"])
    assert 9 not in [r["number"] for r in rows]  # ADR-0009 not surfaced publicly


def test_evals_baseline_endpoint_returns_the_blessed_metrics():
    resp = client.get("/api/evals/baseline")
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_cases"] == 30
    assert 0 <= body["metrics"]["retrieval_hit_at_3"] <= 1


def test_runbooks_endpoint_serves_corpus_markdown():
    path = "corpus/synthetic/paymentsvc/bad-migration-table-lock.md"
    resp = client.get("/api/runbooks", params={"path": path})
    assert resp.status_code == 200
    assert "# " in resp.json()["markdown"]


def test_runbooks_endpoint_refuses_path_traversal():
    for bad in ["../../etc/passwd", "src/runbook/config.py", "/etc/hosts"]:
        resp = client.get("/api/runbooks", params={"path": bad})
        assert resp.status_code in (400, 404), bad


def test_incidents_featured_filter_passes_through(monkeypatch):
    seen = {}

    def fake_list(**kw):
        seen.update(kw)
        return []

    monkeypatch.setattr(web_api, "list_runs", fake_list)
    client.get("/api/incidents", params={"featured": "1"})
    assert seen["featured"] is True
