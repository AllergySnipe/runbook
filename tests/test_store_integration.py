"""The SQL shell around `compute_status` — round-trips a run through
record → get → approve/reject against real Postgres (Neon). Needs
`database_url`; skipped otherwise (CI without a DB, offline unit runs). Every
test cleans up the rows it creates.
"""

from __future__ import annotations

import pytest


def _has_db() -> bool:
    try:
        from runbook.config import get_settings

        return bool(get_settings().database_url)
    except Exception:  # noqa: BLE001 - any config failure means "no DB, skip"
        return False


pytestmark = pytest.mark.skipif(not _has_db(), reason="needs a configured database_url")

from runbook.core import record_run, resolve_approvals
from runbook.core.guardrail import ActionVerdict, GuardrailReport
from runbook.core.loop import DiagnoseResult, Diagnosis, RemediationStep
from runbook.core.triage import TriageResult
from runbook.db import connect


def _result(disposition, steps):
    """steps: list of (action, quote, classification)."""
    verdicts = [
        ActionVerdict(
            step_index=i,
            action=a,
            classification=cls,
            reason="test reason",
            model_flag=(cls == "state-changing"),
            model_disagreed=False,
        )
        for i, (a, _q, cls) in enumerate(steps)
    ]
    diagnosis = None
    guardrail = None
    if disposition is not None:
        diagnosis = Diagnosis(
            summary="s",
            root_cause="rc",
            failure_mode="db-connection-pool-exhaustion",
            confidence="high",
            evidence=["e"],
            remediation_steps=[
                RemediationStep(action=a, runbook_quote=q, state_changing=(cls == "state-changing"))
                for (a, q, cls) in steps
            ],
        )
        guardrail = GuardrailReport(verdicts=verdicts)
    return DiagnoseResult(
        alert="integration-test alert",
        scenario="db-connection-pool-exhaustion",
        triage=TriageResult(category="known-runbook", rationale="r", confidence="high"),
        diagnosis=diagnosis,
        guardrail=guardrail,
        disposition=disposition,
        retrieved=[],
        tool_calls=[],
        iterations=1,
        hit_max_iters=False,
        grounding_issues=[],
        usage={"input_tokens": 1, "output_tokens": 1},
        elapsed_s=1.0,
    )


def _delete(run_id: str) -> None:
    with connect() as conn, conn.transaction():
        conn.execute("delete from incident_runs where id = %s", (run_id,))


@pytest.fixture
def cleanup():
    ids: list[str] = []
    yield ids
    for run_id in ids:
        _delete(run_id)


def test_needs_approval_round_trip_then_approve(cleanup):
    run = record_run(
        _result(
            "needs-approval",
            [
                ("Check the pool metric", "q1", "read-only"),
                ("Roll back the deploy", "q2", "state-changing"),
            ],
        )
    )
    cleanup.append(run.id)

    assert run.status == "awaiting-approval"
    assert run.resolved_at is None
    assert [a.step_index for a in run.approvals] == [1]  # only the state-changing step
    assert run.approvals[0].state == "pending"

    after = resolve_approvals(run.id, decision="approve", by="tester")
    assert after.status == "resolved"
    assert after.resolved_at is not None
    assert after.approvals[0].state == "approved"
    assert after.approvals[0].resolved_by == "tester"


def test_reject_marks_whole_run_rejected(cleanup):
    run = record_run(_result("needs-approval", [("Roll back the deploy", "q", "state-changing")]))
    cleanup.append(run.id)

    after = resolve_approvals(run.id, decision="reject", by="tester", note="too risky mid-peak")
    assert after.status == "rejected"
    assert after.approvals[0].state == "rejected"
    assert after.approvals[0].note == "too risky mid-peak"


def test_auto_disposition_is_resolved_immediately(cleanup):
    run = record_run(_result("auto", [("Check the pool metric", "q", "read-only")]))
    cleanup.append(run.id)
    assert run.status == "resolved"
    assert run.resolved_at is not None
    assert run.approvals == []


def test_short_circuited_run_persists_with_null_disposition(cleanup):
    run = record_run(_result(None, []))
    cleanup.append(run.id)
    assert run.status == "short-circuited"
    assert run.disposition is None
    assert run.diagnosis is None


def test_resolving_a_terminal_run_is_a_noop(cleanup):
    run = record_run(_result("auto", [("Check X", "q", "read-only")]))
    cleanup.append(run.id)
    after = resolve_approvals(run.id, decision="approve", by="tester")
    assert after.status == "resolved"  # unchanged, no error
