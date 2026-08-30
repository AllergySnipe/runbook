"""`evals/promote.render_case_stub` — the prod→eval flywheel's rendering step
(ADR-0016). Pure: no DB. The stub must be paste-ready Python and must never
present the model's guess as a confirmed label."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import UTC, datetime

from runbook.evals.promote import render_case_stub


@dataclass
class _Run:
    id: str
    alert: str
    scenario: str
    triage_category: str
    disposition: str
    diagnosis: dict | None
    retrieved: list


@dataclass
class _Outcome:
    actual_root_cause: str
    actual_failure_mode: str | None
    created_by: str
    created_at: datetime = datetime(2026, 8, 31, tzinfo=UTC)
    model_was_correct: bool | None = True


def _run(**kw):
    base = {
        "id": "run_abcd1234",
        "alert": "PaymentsvcErrorRateHigh — 5xx on POST /charges over 2% for 5m",
        "scenario": "acquirer-gw-timeouts",
        "triage_category": "known-runbook",
        "disposition": "needs-approval",
        "diagnosis": {"root_cause": "model's guess", "failure_mode": "acquirer-gw-timeouts"},
        "retrieved": [{"path": "corpus/synthetic/paymentsvc/acquirer-gw-timeouts.md"}],
    }
    base.update(kw)
    return _Run(**base)


def _body(stub: str) -> ast.Call:
    """Parse the stub (minus its leading comments) into the EvalCase call node."""
    src = "\n".join(ln for ln in stub.splitlines() if not ln.lstrip().startswith("#"))
    expr = ast.parse(src.strip().rstrip(","), mode="eval")
    assert isinstance(expr.body, ast.Call)
    return expr.body


def test_stub_is_valid_python_with_the_expected_fields():
    call = _body(
        render_case_stub(
            _run(), _Outcome("acquirer-gw partial outage", "acquirer-gw-timeouts", "ritvik")
        )
    )
    kw = {k.arg for k in call.keywords}
    assert kw == {
        "id",
        "alert",
        "scenario",
        "expect_triage",
        "expect_runbook",
        "expect_failure_mode",
        "expect_disposition",
        "reference_root_cause",
        "notes",
    }


def test_confirmed_outcome_becomes_the_reference_root_cause():
    stub = render_case_stub(
        _run(), _Outcome("acquirer-gw had a partial outage", "acquirer-gw-timeouts", "ritvik")
    )
    assert "acquirer-gw had a partial outage" in stub
    assert "human-confirmed by ritvik" in stub
    assert "model's guess" not in stub


def test_without_an_outcome_the_model_guess_is_loudly_flagged():
    stub = render_case_stub(_run(), None)
    assert "model's guess" in stub.lower()
    assert "UNVERIFIED" in stub
    assert "NO recorded outcome" in stub


def test_triage_category_maps_to_the_module_constant():
    assert "expect_triage=TRIAGE_KNOWN" in render_case_stub(_run(), None)
    assert "expect_triage=TRIAGE_NOVEL" in render_case_stub(
        _run(triage_category="novel-incident"), None
    )


def test_long_alert_wraps_without_gluing_words():
    long_alert = (
        "PaymentsvcErrorRateHigh crossed the threshold and the external card "
        "processor slowed down and customers could not complete payments at all"
    )
    stub = render_case_stub(_run(alert=long_alert), _Outcome("x", None, "t"))
    # every original word survives with its spaces (no "downand" / "processorslowed")
    src = _body(stub)
    alert_val = next(k.value for k in src.keywords if k.arg == "alert")
    rendered = ast.literal_eval(alert_val)
    assert rendered == long_alert
