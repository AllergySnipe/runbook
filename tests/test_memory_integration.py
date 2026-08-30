"""The SQL shell around incident memory (`core/memory.py`) — round-trips an
outcome through record → search → get against real Postgres (Neon) + a real
`JINA_API_KEY` (the alert embedding). Skipped otherwise. Every test cleans up
the rows it creates (the `incident_runs` cascade takes `incident_memory` with it).
"""

from __future__ import annotations

import pytest


def _ready() -> bool:
    try:
        from runbook.config import get_settings

        s = get_settings()
        return (
            bool(s.database_url) and bool(s.jina_api_key) and s.jina_api_key != "test-key-not-real"
        )
    except Exception:  # noqa: BLE001 - any config failure means "skip"
        return False


pytestmark = pytest.mark.skipif(not _ready(), reason="needs DATABASE_URL + a real JINA_API_KEY")

import secrets

from runbook.core.memory import get_outcome, record_outcome, search
from runbook.db import connect


def _seed_run(status: str, *, alert: str, root_cause: str = "model guess") -> str:
    run_id = "run_test_" + secrets.token_hex(4)
    with connect() as conn, conn.transaction():
        conn.execute(
            """
            insert into incident_runs (id, alert, scenario, triage_category,
                triage_rationale, triage_confidence, disposition, status, diagnosis)
            values (%s, %s, 'acquirer-gw-timeouts', 'known-runbook', 'r', 'high',
                    'needs-approval', %s, jsonb_build_object('root_cause', %s::text))
            """,
            (run_id, alert, status, root_cause),
        )
    return run_id


@pytest.fixture
def cleanup():
    ids: list[str] = []
    yield ids
    for run_id in ids:
        with connect() as conn, conn.transaction():
            conn.execute("delete from incident_runs where id = %s", (run_id,))


def test_record_then_search_then_get(cleanup):
    alert = "PaymentsvcErrorRateHigh — 5xx rate on POST /charges over 2% for 5m"
    run_id = _seed_run("resolved", alert=alert, root_cause="pool exhaustion (wrong)")
    cleanup.append(run_id)

    res = record_outcome(
        run_id,
        actual_root_cause="acquirer-gw partial outage; synchronous charge path surfaced it",
        actual_failure_mode="acquirer-gw-timeouts",
        model_was_correct=False,
        by="tester",
    )
    assert res.status == "stored"
    assert res.entry_id is not None

    # idempotent on run_id
    assert (
        record_outcome(run_id, actual_root_cause="x", model_was_correct=None, by="tester").status
        == "exists"
    )

    oc = get_outcome(run_id)
    assert oc is not None
    assert oc.model_was_correct is False
    assert oc.actual_failure_mode == "acquirer-gw-timeouts"
    assert oc.created_by == "tester"

    from runbook.embed import embed_query

    hits = search(embed_query(alert + " (retry)"), n=3)
    assert any(h.entry_id == res.entry_id for h in hits)
    hit = next(h for h in hits if h.entry_id == res.entry_id)
    assert hit.model_root_cause == "pool exhaustion (wrong)"
    assert hit.model_was_correct is False


def test_ineligible_status_is_rejected(cleanup):
    run_id = _seed_run("awaiting-approval", alert="some alert about charges failing")
    cleanup.append(run_id)
    with pytest.raises(ValueError, match="record an outcome only once"):
        record_outcome(run_id, actual_root_cause="rc", model_was_correct=None, by="tester")


def test_unknown_run_raises_lookup(cleanup):
    with pytest.raises(LookupError):
        record_outcome("run_does_not_exist", actual_root_cause="rc", model_was_correct=None, by="t")


def test_near_duplicate_incident_is_not_stored_twice(cleanup):
    alert = "acquirer gw timing out, charges 502ing, retry ratio climbing fast"
    a = _seed_run("resolved", alert=alert)
    b = _seed_run("escalated", alert=alert + " still")
    cleanup += [a, b]

    first = record_outcome(a, actual_root_cause="acquirer outage", model_was_correct=True, by="t")
    assert first.status == "stored"

    second = record_outcome(
        b, actual_root_cause="acquirer outage again", model_was_correct=True, by="t"
    )
    assert second.status == "deduped"
    assert second.similar_to == first.entry_id
