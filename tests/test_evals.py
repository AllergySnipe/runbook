"""The eval harness is deterministic code (the scorers, the aggregation, the
baseline gate, the runner's control flow) — so it gets pytest. Whether the real
model passes the golden set is the eval itself (`runbook eval`), not this file.

No API calls, no DB: fake `DiagnoseResult`s for the scorers, a monkeypatched
`diagnose` + `judge` for the runner.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from runbook.core.guardrail import ActionVerdict, GuardrailReport
from runbook.core.loop import DiagnoseResult, Diagnosis, GroundingIssue, RemediationStep, ToolCall
from runbook.core.triage import TriageResult
from runbook.evals import CASES
from runbook.evals.cases import EvalCase
from runbook.evals.report import METRICS, EvalReport
from runbook.evals.runner import run_evals
from runbook.evals.scorers import score_case

# --------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------


def _chunk(path: str):
    return SimpleNamespace(path=path)


def _verdict(i, cls, action="do a thing"):
    return ActionVerdict(
        step_index=i,
        action=action,
        classification=cls,
        reason="test",
        model_flag=(cls == "state-changing"),
        model_disagreed=False,
    )


def _diagnosis(failure_mode="db-connection-pool-exhaustion", steps=None):
    return Diagnosis(
        summary="s",
        root_cause="rc",
        failure_mode=failure_mode,
        confidence="high",
        evidence=["e"],
        remediation_steps=steps
        if steps is not None
        else [
            RemediationStep(
                action="Roll back the deploy", runbook_quote="roll back", state_changing=True
            )
        ],
    )


def _result(
    *,
    scenario="db-connection-pool-exhaustion",
    triage_cat="known-runbook",
    diagnosis="default",
    disposition="needs-approval",
    verdicts="default",
    retrieved=("db-connection-pool-exhaustion.md",),
    tool_calls=(),
    grounding_issues=(),
):
    d = _diagnosis() if diagnosis == "default" else diagnosis
    if verdicts == "default":
        vs = [_verdict(0, "state-changing")] if d and d.remediation_steps else []
    else:
        vs = verdicts
    guardrail = None if d is None else GuardrailReport(verdicts=list(vs))
    return DiagnoseResult(
        alert="a",
        scenario=scenario,
        triage=TriageResult(category=triage_cat, rationale="r", confidence="high"),
        diagnosis=d,
        guardrail=guardrail,
        disposition=disposition,
        retrieved=[_chunk(f"corpus/synthetic/paymentsvc/{p}") for p in retrieved],
        tool_calls=[ToolCall(n, {}, "{}", False) for n in tool_calls],
        iterations=2,
        hit_max_iters=False,
        grounding_issues=list(grounding_issues),
        usage={"input_tokens": 100, "output_tokens": 40},
        elapsed_s=3.0,
    )


def _case(**kw):
    base = {
        "id": "t/case",
        "alert": "a",
        "scenario": "db-connection-pool-exhaustion",
        "expect_triage": "known-runbook",
        "expect_runbook": "db-connection-pool-exhaustion.md",
        "expect_failure_mode": "db-connection-pool-exhaustion",
        "expect_disposition": "needs-approval",
        "reference_root_cause": "ref",
    }
    base.update(kw)
    return EvalCase(**base)


# --------------------------------------------------------------------------
# hard checks
# --------------------------------------------------------------------------


def test_clean_needs_approval_has_no_hard_findings():
    s = score_case(_case(), _result())
    assert s.hard_ok
    assert s.triage_correct and s.disposition_correct
    assert s.retrieval_hit_at_3 is True
    assert s.failure_mode_correct is True
    assert s.triage_incident_recalled is True


def test_action_safety_flags_state_changing_step_on_auto_disposition():
    r = _result(disposition="auto", verdicts=[_verdict(0, "state-changing")])
    s = score_case(_case(expect_disposition="auto"), r)
    checks = {f.check for f in s.hard_findings}
    assert "action-safety" in checks


def test_action_safety_ok_when_state_changing_step_gets_needs_approval():
    r = _result(disposition="needs-approval", verdicts=[_verdict(0, "state-changing")])
    assert score_case(_case(), r).hard_ok


def test_tool_allowlist_flags_off_list_tool():
    r = _result(tool_calls=("query_metrics", "rm_minus_rf"))
    s = score_case(_case(), r)
    assert any(f.check == "tool-allowlist" for f in s.hard_findings)


def test_tool_allowlist_ok_for_real_tools():
    r = _result(tool_calls=("query_metrics", "search_logs", "get_recent_deploys"))
    assert score_case(_case(), r).hard_ok


def test_groundedness_flags_ungrounded_needs_approval():
    r = _result(
        disposition="needs-approval",
        grounding_issues=[GroundingIssue(0, "bad", "quote not found in retrieved runbook")],
    )
    s = score_case(_case(), r)
    assert any(f.check == "groundedness" for f in s.hard_findings)


def test_groundedness_ok_on_escalate_with_no_steps():
    r = _result(diagnosis=_diagnosis(steps=[]), disposition="escalate", verdicts=[])
    s = score_case(_case(expect_disposition="escalate"), r)
    assert s.hard_ok


def test_short_circuit_has_no_hard_findings_and_na_soft_scores():
    r = _result(triage_cat="noise-or-flapping", diagnosis=None, disposition=None, retrieved=())
    c = _case(
        expect_triage="noise-or-flapping",
        expect_runbook=None,
        expect_failure_mode=None,
        expect_disposition="short-circuit",
    )
    s = score_case(c, r)
    assert s.hard_ok
    assert s.triage_correct and s.disposition_correct
    assert s.retrieval_hit_at_3 is None
    assert s.failure_mode_correct is None
    assert s.triage_incident_recalled is None


# --------------------------------------------------------------------------
# soft scores
# --------------------------------------------------------------------------


def test_triage_and_incident_recall_miss():
    # a real incident wrongly called noise
    r = _result(triage_cat="noise-or-flapping", diagnosis=None, disposition=None, retrieved=())
    s = score_case(_case(), r)
    assert s.triage_correct is False
    assert s.triage_incident_recalled is False


def test_retrieval_miss_when_expected_not_in_top3():
    r = _result(
        retrieved=("acquirer-gw-timeouts.md", "redis-eviction-idempotency.md", "healthy.md")
    )
    assert score_case(_case(), r).retrieval_hit_at_3 is False


def test_failure_mode_miss():
    r = _result(diagnosis=_diagnosis(failure_mode="acquirer-gw-timeouts"))
    assert score_case(_case(), r).failure_mode_correct is False


# --------------------------------------------------------------------------
# aggregation + baseline gate
# --------------------------------------------------------------------------


def _outcome(case, result, judge_score=None):
    from runbook.evals.report import CaseOutcome

    j = SimpleNamespace(score=judge_score, rationale="x") if judge_score is not None else None
    return CaseOutcome(case, result, None, score_case(case, result), j, 1.0, result.usage)


def test_report_metrics_and_below_target():
    good = _outcome(_case(id="a"), _result(), judge_score=5)
    bad = _outcome(
        _case(id="b"),
        _result(diagnosis=_diagnosis(failure_mode="wrong")),
        judge_score=2,
    )
    rep = EvalReport.from_outcomes([good, bad])
    assert rep.metrics["failure_mode_exact"] == 0.5
    assert rep.metrics["triage_accuracy"] == 1.0
    assert rep.metrics["judge_mean_norm"] == pytest.approx(0.7)
    assert "failure_mode_exact 0.50 < target 0.80" in rep.below_target()


def test_regression_only_when_below_baseline_and_target():
    rep = EvalReport.from_outcomes(
        [_outcome(_case(), _result(diagnosis=_diagnosis(failure_mode="wrong")))]
    )
    # failure_mode_exact = 0.0 here
    assert rep.regressions({"metrics": {"failure_mode_exact": 0.9}})  # dropped and below target
    # a drop that stays above target is tolerated
    rep2 = EvalReport.from_outcomes([_outcome(_case(id="x"), _result())])  # fm exact = 1.0
    assert not rep2.regressions({"metrics": {"failure_mode_exact": 1.0}})


def test_errored_case_fails_the_report():
    from runbook.evals.report import CaseOutcome

    err = CaseOutcome(_case(), None, "RuntimeError('boom')", None, None, 0.1, {})
    rep = EvalReport.from_outcomes([err])
    assert rep.n_errored == 1
    assert not rep.passed(None)
    assert "ERRORED" in rep.format()


def test_bless_from_json_round_trips_and_refuses_dirty_runs(tmp_path, monkeypatch):
    import json

    from runbook.evals import report as rpt

    monkeypatch.setattr(rpt, "BASELINE_PATH", tmp_path / "baseline.json")

    clean = tmp_path / "clean.json"
    clean.write_text(
        json.dumps(
            {
                "generated_at": "2026-08-30T00:00:00+00:00",
                "n_cases": 30,
                "n_errored": 0,
                "hard_findings": [],
                "metrics": {"triage_accuracy": 0.933333, "judge_mean_norm": 0.9},
            }
        )
    )
    metrics = rpt.bless_from_json(str(clean))
    assert metrics["judge_mean_norm"] == 0.9
    written = json.loads((tmp_path / "baseline.json").read_text())
    assert written["metrics"]["triage_accuracy"] == 0.9333  # rounded to 4dp
    assert written["blessed_at"] == "2026-08-30T00:00:00+00:00"

    dirty = tmp_path / "dirty.json"
    dirty.write_text(json.dumps({"generated_at": "x", "n_cases": 1, "n_errored": 3, "metrics": {}}))
    with pytest.raises(ValueError, match="errored"):
        rpt.bless_from_json(str(dirty))


# --------------------------------------------------------------------------
# runner control flow (fake diagnose + judge)
# --------------------------------------------------------------------------


def test_runner_scores_and_judges(monkeypatch):
    async def fake_diagnose(alert, scenario, **kw):
        return _result(scenario=scenario)

    async def fake_judge(case, result, **kw):
        return SimpleNamespace(score=4, rationale="ok"), SimpleNamespace(
            input_tokens=10, output_tokens=3
        )

    monkeypatch.setattr("runbook.evals.runner.diagnose", fake_diagnose)
    monkeypatch.setattr("runbook.evals.runner.judge", fake_judge)

    cases = [_case(id="one"), _case(id="two")]
    rep = asyncio.run(run_evals(cases, concurrency=2))
    assert rep.n_cases == 2 and rep.n_errored == 0
    assert rep.n_judged == 2
    assert rep.metrics["judge_mean_norm"] == pytest.approx(0.8)
    assert rep.tokens["input_tokens"] == 2 * (100 + 10)


def test_runner_catches_a_crashing_case(monkeypatch):
    async def boom(alert, scenario, **kw):
        raise RuntimeError("loop exploded")

    monkeypatch.setattr("runbook.evals.runner.diagnose", boom)
    rep = asyncio.run(run_evals([_case(id="x")], use_judge=False))
    assert rep.n_errored == 1
    assert not rep.passed(None)


def test_runner_no_judge_skips_judging(monkeypatch):
    async def fake_diagnose(alert, scenario, **kw):
        return _result(scenario=scenario)

    def nope(*a, **k):
        raise AssertionError("judge should not be called")

    monkeypatch.setattr("runbook.evals.runner.diagnose", fake_diagnose)
    monkeypatch.setattr("runbook.evals.runner.judge", nope)
    rep = asyncio.run(run_evals([_case()], use_judge=False))
    assert rep.n_judged == 0
    assert rep.metrics["judge_mean_norm"] is None


# --------------------------------------------------------------------------
# the golden set itself
# --------------------------------------------------------------------------


def test_cases_are_wellformed():
    valid_triage = {"known-runbook", "novel-incident", "noise-or-flapping", "need-more-info"}
    valid_disp = {"auto", "needs-approval", "escalate", "short-circuit"}
    scenarios = set()
    for c in CASES:
        assert c.expect_triage in valid_triage, c.id
        assert set(c.expect_disposition.split("|")) <= valid_disp, c.id
        assert c.reference_root_cause, c.id
        if c.expect_triage in {"noise-or-flapping", "need-more-info"}:
            assert c.expect_disposition == "short-circuit", c.id
            assert c.expect_runbook is None and c.expect_failure_mode is None, c.id
        if c.expect_triage == "known-runbook":
            assert c.expect_runbook and c.expect_failure_mode, c.id
        scenarios.add(c.scenario)
    # every incident sim scenario is represented
    assert scenarios >= {
        "acquirer-gw-timeouts",
        "bad-migration-table-lock",
        "db-connection-pool-exhaustion",
        "noisy-neighbour-cpu-throttling",
        "payments-events-consumer-lag",
        "redis-eviction-idempotency",
    }


def test_case_count_in_expected_range():
    assert 28 <= len(CASES) <= 60


def test_every_metric_has_a_spec():
    rep = EvalReport.from_outcomes([_outcome(_case(), _result(), judge_score=5)])
    spec_names = {m.name for m in METRICS}
    assert set(rep.metrics) == spec_names
