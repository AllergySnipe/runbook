"""Online scoring (ADR-0018) is deterministic code — the reference-free scorers,
the sampling gate, the low-score rules — so it gets pytest. Whether the scores
are *useful* on real traffic is a judgement call made by reading the Langfuse
dashboard, not this file.

No DB, no model: fake `DiagnoseResult`s. `score_and_record` (which touches
Postgres + Langfuse) is exercised in `test_scoring_integration.py`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runbook.core import scoring
from runbook.core.guardrail import ActionVerdict, GuardrailReport
from runbook.core.loop import DiagnoseResult, Diagnosis, GroundingIssue, RemediationStep, ToolCall
from runbook.core.triage import TriageResult

# --- builders --------------------------------------------------------------


def _step(action="Restart the pool", quote="restart the connection pool", state_changing=False):
    return RemediationStep(action=action, runbook_quote=quote, state_changing=state_changing)


def _diagnosis(steps=None):
    return Diagnosis(
        summary="s",
        root_cause="rc",
        failure_mode="db-connection-pool-exhaustion",
        confidence="high",
        evidence=["e"],
        remediation_steps=[_step()] if steps is None else steps,
    )


def _chunk(path="corpus/synthetic/paymentsvc/x.md", scores=None):
    return SimpleNamespace(path=path, scores=scores if scores is not None else {"rerank": 0.82})


def _result(
    *,
    diagnosis="default",
    disposition="auto",
    verdicts=(),
    retrieved="default",
    tool_calls=(),
    grounding_issues=(),
):
    d = _diagnosis() if diagnosis == "default" else diagnosis
    guardrail = None if d is None else GuardrailReport(verdicts=list(verdicts))
    if retrieved == "default":
        retrieved = [_chunk()]
    return DiagnoseResult(
        alert="a",
        scenario="db-connection-pool-exhaustion",
        triage=TriageResult(category="known-runbook", rationale="r", confidence="high"),
        diagnosis=d,
        guardrail=guardrail,
        disposition=disposition,
        retrieved=list(retrieved),
        tool_calls=[ToolCall(n, {}, "{}", False) for n in tool_calls],
        iterations=2,
        hit_max_iters=False,
        grounding_issues=list(grounding_issues),
        usage={"input_tokens": 1, "output_tokens": 1},
        elapsed_s=1.0,
    )


def _verdict(i, cls):
    return ActionVerdict(
        step_index=i,
        action="do a thing",
        classification=cls,
        reason="t",
        model_flag=(cls == "state-changing"),
        model_disagreed=False,
    )


def _by_name(scores):
    return {s.name: s for s in scores}


# --- safety-invariants ----------------------------------------------------


def test_safety_invariants_pass_on_a_clean_auto_run():
    s = _by_name(scoring.score_run(_result()))["safety-invariants"]
    assert s.data_type == "BOOLEAN"
    assert s.value == 1.0
    assert s.comment is None


def test_safety_invariants_flag_state_changing_step_not_gated():
    r = _result(disposition="auto", verdicts=[_verdict(0, "state-changing")])
    s = _by_name(scoring.score_run(r))["safety-invariants"]
    assert s.value == 0.0
    assert "S1" in s.comment


def test_safety_invariants_flag_off_allowlist_tool_call():
    r = _result(tool_calls=["totally_not_a_tool"])
    s = _by_name(scoring.score_run(r))["safety-invariants"]
    assert s.value == 0.0
    assert "S2" in s.comment and "totally_not_a_tool" in s.comment


def test_safety_invariants_flag_ungrounded_proposal():
    r = _result(
        grounding_issues=[GroundingIssue(0, "made up", "quote not found in retrieved runbook")]
    )
    s = _by_name(scoring.score_run(r))["safety-invariants"]
    assert s.value == 0.0
    assert "S3" in s.comment


def test_safety_invariants_ok_when_state_changing_step_is_gated():
    r = _result(disposition="needs-approval", verdicts=[_verdict(0, "state-changing")])
    assert _by_name(scoring.score_run(r))["safety-invariants"].value == 1.0


def test_safety_invariants_ok_on_an_escalation_with_no_steps():
    r = _result(diagnosis=_diagnosis(steps=[]), disposition="escalate")
    assert _by_name(scoring.score_run(r))["safety-invariants"].value == 1.0


# --- grounding-coverage -------------------------------------------------------


def test_grounding_coverage_full():
    s = _by_name(scoring.score_run(_result(diagnosis=_diagnosis(steps=[_step(), _step()]))))
    assert s["grounding-coverage"].value == 1.0


def test_grounding_coverage_partial():
    r = _result(
        diagnosis=_diagnosis(steps=[_step(), _step()]),
        grounding_issues=[GroundingIssue(1, "x", "quote not found in retrieved runbook")],
    )
    assert _by_name(scoring.score_run(r))["grounding-coverage"].value == 0.5


def test_grounding_coverage_absent_when_no_proposal():
    r = _result(diagnosis=None, disposition=None, retrieved=[])
    assert "grounding-coverage" not in _by_name(scoring.score_run(r))


# --- retrieval-confidence --------------------------------------------------


def test_retrieval_confidence_uses_rerank_score():
    r = _result(retrieved=[_chunk(scores={"rerank": 0.91, "rrf": 0.03})])
    assert _by_name(scoring.score_run(r))["retrieval-confidence"].value == 0.91


def test_retrieval_confidence_falls_back_to_rrf():
    r = _result(retrieved=[_chunk(scores={"rrf": 0.0164})])
    assert _by_name(scoring.score_run(r))["retrieval-confidence"].value == 0.0164


def test_retrieval_confidence_absent_when_nothing_retrieved():
    r = _result(diagnosis=None, disposition=None, retrieved=[])
    assert "retrieval-confidence" not in _by_name(scoring.score_run(r))


def test_retrieval_confidence_absent_when_scores_missing():
    r = _result(retrieved=[_chunk(scores={})])
    assert "retrieval-confidence" not in _by_name(scoring.score_run(r))


# --- disposition -----------------------------------------------------------


def test_disposition_passthrough():
    s = _by_name(scoring.score_run(_result(disposition="needs-approval")))["disposition"]
    assert s.data_type == "CATEGORICAL"
    assert s.value == "needs-approval"


def test_disposition_short_circuit():
    r = _result(diagnosis=None, disposition=None, retrieved=[])
    assert _by_name(scoring.score_run(r))["disposition"].value == "short-circuit"


# --- sampling + low-score rules ------------------------------------------


def test_should_score_off_when_disabled(monkeypatch):
    monkeypatch.setattr(
        scoring,
        "get_settings",
        lambda: SimpleNamespace(scoring_enabled=False, scoring_sample_rate=1.0),
    )
    assert scoring.should_score() is False


def test_should_score_rate_zero_never(monkeypatch):
    monkeypatch.setattr(
        scoring,
        "get_settings",
        lambda: SimpleNamespace(scoring_enabled=True, scoring_sample_rate=0.0),
    )
    assert scoring.should_score() is False


def test_should_score_rate_one_always(monkeypatch):
    monkeypatch.setattr(
        scoring,
        "get_settings",
        lambda: SimpleNamespace(scoring_enabled=True, scoring_sample_rate=1.0),
    )
    assert scoring.should_score() is True


def test_is_low_rules():
    assert scoring.is_low("safety-invariants", 0.0) is True
    assert scoring.is_low("safety-invariants", 1.0) is False
    assert scoring.is_low("grounding-coverage", 0.5) is True
    assert scoring.is_low("grounding-coverage", 0.9) is False
    assert scoring.is_low("retrieval-confidence", 0.1) is True
    assert scoring.is_low("disposition", "escalate") is False  # no rule → never "low"
    assert scoring.is_low("unknown-metric", 0.0) is False


# --- kept in sync with the eval suite's hard checks ---------------------


@pytest.mark.parametrize(
    "r",
    [
        _result(),
        _result(disposition="auto", verdicts=[_verdict(0, "state-changing")]),
        _result(tool_calls=["not_a_tool"]),
        _result(grounding_issues=[GroundingIssue(0, "x", "quote not found in retrieved runbook")]),
        _result(disposition="needs-approval", verdicts=[_verdict(0, "state-changing")]),
        _result(diagnosis=_diagnosis(steps=[]), disposition="escalate"),
    ],
)
def test_consistent_with_eval_hard_checks(r):
    """`safety-invariants == 0` iff the eval suite's hard checks would fail the
    same run — the two S1-S3 implementations must not drift."""
    from runbook.evals.cases import EvalCase
    from runbook.evals.scorers import score_case

    case = EvalCase(
        id="sync/test",
        alert="a",
        scenario="db-connection-pool-exhaustion",
        expect_triage="known-runbook",
        expect_runbook=None,
        expect_failure_mode=None,
        expect_disposition="auto|needs-approval|escalate|short-circuit",
        reference_root_cause="ref",
    )
    hard_ok = not score_case(case, r).hard_findings
    online_ok = scoring.score_run(r)[0].value == 1.0  # score_run puts safety-invariants first
    assert online_ok is hard_ok
