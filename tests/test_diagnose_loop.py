"""The diagnosis loop, driven by a fake model — no API calls, no DB.

The loop logic (tool-result threading, the iteration cap, grounding check) is
deterministic and gets unit coverage here. Whether the *real* model reaches a
good diagnosis is a manual check now and an eval in Week 2.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from runbook.core import loop as diag
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


def _diagnosis(quote: str) -> diag.Diagnosis:
    return diag.Diagnosis(
        summary="pool exhausted",
        root_cause="every query holds its connection longer after a query regression",
        failure_mode="db-connection-pool-exhaustion",
        confidence="high",
        evidence=["paymentsvc_db_pool_checked_out pinned at 20 = pool size"],
        remediation_steps=[
            diag.RemediationStep(
                action="Roll back the deploy", runbook_quote=quote, state_changing=True
            )
        ],
    )


def _run(monkeypatch, *, turns, diagnosis, max_iters=8):
    """Wire fakes and run diagnose(). `turns` is a list of (stop_reason, content)."""
    monkeypatch.setattr(diag, "retrieve", lambda *a, **k: [_chunk()])

    calls = {"n": 0}

    async def fake_run_turn(messages, **kw):
        i = calls["n"]
        calls["n"] += 1
        stop, content = turns[min(i, len(turns) - 1)]
        return SimpleNamespace(stop_reason=stop, content=content, usage=_usage())

    async def fake_parse(messages, **kw):
        return diagnosis, _usage(100, 40)

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
    assert result.usage["input_tokens"] == 10 + 10 + 100  # two turns + synthesis
    assert result.diagnosis.failure_mode == "db-connection-pool-exhaustion"


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


def test_ungrounded_step_is_flagged(monkeypatch):
    turns = [("end_turn", [_text_block("done")])]
    result = _run(
        monkeypatch,
        turns=turns,
        diagnosis=_diagnosis("Reboot the universe and hope for the best"),
    )

    assert result.grounding_issues
    assert result.grounding_issues[0].reason == "quote not found in retrieved runbook"
    assert not result.grounded


def test_bad_tool_arguments_come_back_as_an_error_result(monkeypatch):
    turns = [
        ("tool_use", [_tool_block("query_metrics", {"bogus_arg": 1})]),
        ("end_turn", [_text_block("ok")]),
    ]
    result = _run(monkeypatch, turns=turns, diagnosis=_diagnosis("Roll back the implicated deploy"))

    assert result.tool_calls[0].is_error is True
    assert "bad arguments" in result.tool_calls[0].result_json


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
