"""The diagnosis loop, driven by a fake model — no API calls, no DB.

The loop logic (tool-result threading, the iteration cap, grounding enforcement,
guardrail wiring, disposition) is deterministic and gets unit coverage here.
Whether the *real* model reaches a good diagnosis is a manual check now and an
eval in Week 2.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from runbook.core import loop as diag
from runbook.core.guardrail import SecondPassConcern
from runbook.rag import RetrievedChunk

RUNBOOK_TEXT = (
    "# paymentsvc — Database connection-pool exhaustion\n"
    "Diagnosis: query_metrics paymentsvc_db_pool_checked_out vs paymentsvc_db_pool_size.\n"
    "Remediation: [read-only] Confirm scope — is it one pod or all?\n"
    "[state-changing — needs approval] Roll back the implicated deploy.\n"
)


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        id=1,
        title="paymentsvc — Database connection-pool exhaustion",
        url=None,
        source="synthetic-runbook",
        origin="paymentsvc",
        path="corpus/synthetic/paymentsvc/db-connection-pool-exhaustion.md",
        heading_path=["Diagnosis"],
        chunk_text=RUNBOOK_TEXT,
    )


def _usage(i=10, o=5):
    return SimpleNamespace(input_tokens=i, output_tokens=o)


def _text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _tool_block(name: str, tool_input: dict, id_: str = "tu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=id_)


def _diagnosis(
    quote: str, *, action: str = "Roll back the deploy", state_changing: bool = True
) -> diag.Diagnosis:
    return diag.Diagnosis(
        summary="pool exhausted",
        root_cause="every query holds its connection longer after a query regression",
        failure_mode="db-connection-pool-exhaustion",
        confidence="high",
        evidence=["paymentsvc_db_pool_checked_out pinned at 20 = pool size"],
        remediation_steps=[
            diag.RemediationStep(action=action, runbook_quote=quote, state_changing=state_changing)
        ],
    )


def _readonly_diagnosis() -> diag.Diagnosis:
    return diag.Diagnosis(
        summary="pool exhausted",
        root_cause="query regression after a deploy",
        failure_mode="db-connection-pool-exhaustion",
        confidence="medium",
        evidence=["pool checked-out pinned at size"],
        remediation_steps=[
            diag.RemediationStep(
                action="Confirm scope — is this one pod or all pods?",
                runbook_quote="Confirm scope — is it one pod or all?",
                state_changing=False,
            )
        ],
    )


def _triage(category: str = "known-runbook") -> diag.TriageResult:
    return diag.TriageResult(category=category, rationale="fake", confidence="high")


def _run(monkeypatch, *, turns, diagnosis, max_iters=8, triage=None, second_pass_concerns=None):
    """Wire fakes and run diagnose().

    `turns` is a list of (stop_reason, content). `diagnosis` is a Diagnosis or a
    list of them (one per synthesis call, for the grounding-regenerate path).
    """
    monkeypatch.setattr(diag, "retrieve", lambda *a, **k: [_chunk()])

    calls = {"n": 0}
    syn_calls = {"n": 0}
    triage_result = triage or _triage()
    diag_seq = diagnosis if isinstance(diagnosis, list) else [diagnosis]
    concerns = second_pass_concerns or []

    async def fake_run_turn(messages, **kw):
        i = calls["n"]
        calls["n"] += 1
        stop, content = turns[min(i, len(turns) - 1)]
        return SimpleNamespace(stop_reason=stop, content=content, usage=_usage())

    async def fake_parse(messages, *, schema, **kw):
        name = getattr(schema, "__name__", "")
        if schema is diag.TriageResult:
            return triage_result, _usage(20, 10)
        if name == "SecondPassReport":
            return schema(concerns=concerns), _usage(15, 5)
        i = min(syn_calls["n"], len(diag_seq) - 1)
        syn_calls["n"] += 1
        return diag_seq[i], _usage(100, 40)

    monkeypatch.setattr(diag.llm, "run_turn", fake_run_turn)
    monkeypatch.setattr(diag.llm, "parse", fake_parse)

    return asyncio.get_event_loop().run_until_complete(
        diag.diagnose(
            "PaymentsvcP99LatencyHigh", "db-connection-pool-exhaustion", max_iters=max_iters
        )
    )


def test_happy_path_one_tool_then_answer(monkeypatch):
    turns = [
        ("tool_use", [_tool_block("query_metrics", {"metric": "paymentsvc_db_pool_checked_out"})]),
        ("end_turn", [_text_block("pool is pinned at size")]),
    ]
    result = _run(monkeypatch, turns=turns, diagnosis=_diagnosis("Roll back the implicated deploy"))

    assert result.iterations == 2
    assert not result.hit_max_iters
    assert [tc.name for tc in result.tool_calls] == ["query_metrics"]
    assert result.tool_calls[0].is_error is False
    assert result.grounding_issues == []
    assert result.grounded
    # two turns + synthesis + second pass
    assert result.usage["input_tokens"] == 10 + 10 + 100 + 15
    assert result.diagnosis.failure_mode == "db-connection-pool-exhaustion"
    assert result.disposition == "needs-approval"
    assert result.guardrail.any_state_changing
    assert result.guardrail.second_pass_ran
    assert not result.guardrail.regenerated_for_grounding


def test_read_only_proposal_is_auto(monkeypatch):
    turns = [("end_turn", [_text_block("checked")])]
    result = _run(monkeypatch, turns=turns, diagnosis=_readonly_diagnosis())

    assert result.disposition == "auto"
    assert not result.guardrail.any_state_changing
    assert result.grounded
    assert not result.escalate


def test_model_underlabelled_state_changing_step_is_caught(monkeypatch):
    turns = [("end_turn", [_text_block("done")])]
    result = _run(
        monkeypatch,
        turns=turns,
        diagnosis=_diagnosis(
            "Roll back the implicated deploy", action="Roll back the deploy", state_changing=False
        ),
    )

    v = result.guardrail.verdicts[0]
    assert v.classification == "state-changing"
    assert v.model_disagreed
    assert result.disposition == "needs-approval"


def test_second_pass_upgrades_a_read_only_step(monkeypatch):
    turns = [("end_turn", [_text_block("done")])]
    result = _run(
        monkeypatch,
        turns=turns,
        diagnosis=_readonly_diagnosis(),
        second_pass_concerns=[
            SecondPassConcern(
                step_index=0, kind="should-be-state-changing", detail="this restarts the pod"
            )
        ],
    )

    v = result.guardrail.verdicts[0]
    assert v.classification == "state-changing"
    assert v.upgraded_by_second_pass
    assert result.disposition == "needs-approval"


def test_iteration_cap_still_produces_a_diagnosis(monkeypatch):
    turns = [("tool_use", [_tool_block("search_logs", {"query": "pool timeout"})])]  # never stops
    result = _run(
        monkeypatch,
        turns=turns,
        diagnosis=_diagnosis("Roll back the implicated deploy"),
        max_iters=3,
    )

    assert result.hit_max_iters
    assert result.iterations == 3
    assert len(result.tool_calls) == 3
    assert result.diagnosis is not None
    assert result.disposition == "needs-approval"


def test_ungrounded_step_regenerated_then_dropped_escalates(monkeypatch):
    turns = [("end_turn", [_text_block("done")])]
    # both synthesis calls return the same ungrounded diagnosis
    result = _run(
        monkeypatch,
        turns=turns,
        diagnosis=_diagnosis("Reboot the universe and hope for the best"),
    )

    assert result.guardrail.regenerated_for_grounding
    assert result.guardrail.dropped_ungrounded == 1
    assert result.diagnosis.remediation_steps == []
    assert result.grounding_issues == []
    assert result.disposition == "escalate"
    assert result.escalate
    assert not result.grounded
    assert not result.guardrail.second_pass_ran


def test_grounding_regenerate_succeeds_on_retry(monkeypatch):
    turns = [("end_turn", [_text_block("done")])]
    result = _run(
        monkeypatch,
        turns=turns,
        diagnosis=[
            _diagnosis("Reboot the universe and hope for the best"),  # 1st: ungrounded
            _diagnosis("Roll back the implicated deploy"),  # 2nd: grounded
        ],
    )

    assert result.guardrail.regenerated_for_grounding
    assert result.guardrail.dropped_ungrounded == 0
    assert result.grounding_issues == []
    assert result.disposition == "needs-approval"
    assert result.grounded


def test_bad_tool_arguments_come_back_as_an_error_result(monkeypatch):
    turns = [
        ("tool_use", [_tool_block("query_metrics", {"bogus_arg": 1})]),
        ("end_turn", [_text_block("ok")]),
    ]
    result = _run(monkeypatch, turns=turns, diagnosis=_diagnosis("Roll back the implicated deploy"))

    assert result.tool_calls[0].is_error is True
    assert "bad arguments" in result.tool_calls[0].result_json


def test_triage_short_circuit_skips_the_loop(monkeypatch):
    turns = [("end_turn", [_text_block("should never run")])]
    result = _run(
        monkeypatch,
        turns=turns,
        diagnosis=_diagnosis("Roll back the implicated deploy"),
        triage=_triage("noise-or-flapping"),
    )

    assert result.short_circuited
    assert result.diagnosis is None
    assert result.guardrail is None
    assert result.disposition is None
    assert result.triage.category == "noise-or-flapping"
    assert result.tool_calls == []
    assert result.iterations == 0
    assert not result.grounded
    assert not result.escalate


def test_novel_incident_proceeds_with_low_prior_note(monkeypatch):
    turns = [("end_turn", [_text_block("looked around")])]
    result = _run(
        monkeypatch,
        turns=turns,
        diagnosis=_diagnosis("Roll back the implicated deploy"),
        triage=_triage("novel-incident"),
    )

    assert not result.short_circuited
    assert result.triage.low_prior
    assert result.diagnosis is not None
    assert result.disposition == "needs-approval"


def test_check_grounding_normalises_whitespace_and_case():
    text = "Remediation: [state-changing — needs approval] Roll back the implicated deploy."
    d = _diagnosis("ROLL BACK   the implicated   deploy")
    assert diag._check_grounding(d, text) == []
    assert diag._check_grounding(_diagnosis("not in here at all"), text)


@pytest.fixture(autouse=True)
def _event_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
