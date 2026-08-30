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


def _usage(i=10, o=5, model="fake/parse-model"):
    return SimpleNamespace(input_tokens=i, output_tokens=o, model=model)


def _text_block(text: str) -> dict:
    return {"kind": "text", "text": text}


def _tool_block(name: str, tool_input: dict, id_: str = "tu_1") -> dict:
    return {"kind": "tool", "name": name, "input": tool_input, "id": id_}


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


def _run(
    monkeypatch,
    *,
    turns,
    diagnosis,
    max_iters=8,
    triage=None,
    second_pass_concerns=None,
    on_event=None,
    use_cache=False,
    cache_hit=None,
    store_sink=None,
):
    """Wire fakes and run diagnose().

    `turns` is a list of `(label, [blocks])` — the label is decorative; the blocks
    (`_text_block` / `_tool_block`) decide the `llm.Turn`. `diagnosis` is a
    Diagnosis, or a list (one per synthesis call), or `None` to make synthesis
    raise `LLMParseError` (a refusal / truncation).

    The semantic cache is always stubbed: `embed_query` returns a fixed vector,
    `alert_cache.lookup` returns `cache_hit` (a `CacheHit` or `None`), and
    `alert_cache.store` appends its kwargs to `store_sink` if given.
    """
    monkeypatch.setattr(diag, "retrieve", lambda *a, **k: [_chunk()])
    monkeypatch.setattr(diag, "embed_query", lambda *a, **k: [0.05] * 8)
    monkeypatch.setattr(diag.alert_cache, "lookup", lambda *a, **k: cache_hit)
    monkeypatch.setattr(
        diag.alert_cache,
        "store",
        lambda *a, **k: store_sink.append(k) if store_sink is not None else None,
    )

    calls = {"n": 0}
    syn_calls = {"n": 0}
    triage_result = triage or _triage()
    diag_seq = diagnosis if isinstance(diagnosis, list) else [diagnosis]
    concerns = second_pass_concerns or []

    async def fake_run_turn(messages, **kw):
        i = calls["n"]
        calls["n"] += 1
        _label, blocks = turns[min(i, len(turns) - 1)]
        text = " ".join(b["text"] for b in blocks if b["kind"] == "text")
        reqs = [
            diag.llm.ToolRequest(id=b["id"], name=b["name"], arguments=b["input"])
            for b in blocks
            if b["kind"] == "tool"
        ]
        return diag.llm.Turn(
            text=text,
            tool_requests=reqs,
            stop_reason="tool_calls" if reqs else "stop",
            usage=diag.llm.Usage(10, 5),
            assistant_message={"role": "assistant", "content": text or None},
        )

    async def fake_parse(messages, *, schema, **kw):
        name = getattr(schema, "__name__", "")
        if schema is diag.TriageResult:
            return triage_result, _usage(20, 10)
        if name == "SecondPassReport":
            return schema(concerns=concerns), _usage(15, 5)
        i = min(syn_calls["n"], len(diag_seq) - 1)
        syn_calls["n"] += 1
        d = diag_seq[i]
        if d is None:
            raise diag.llm.LLMParseError("fake: model refused")
        return d, _usage(100, 40)

    monkeypatch.setattr(diag.llm, "run_turn", fake_run_turn)
    monkeypatch.setattr(diag.llm, "parse", fake_parse)

    return asyncio.get_event_loop().run_until_complete(
        diag.diagnose(
            "PaymentsvcP99LatencyHigh",
            "db-connection-pool-exhaustion",
            max_iters=max_iters,
            on_event=on_event,
            use_cache=use_cache,
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
    # tracing is off in the deterministic suite (ADR-0017) — the trace wrapper is
    # transparent: same result, no trace id/url stamped
    assert result.langfuse_trace_id is None
    assert result.langfuse_trace_url is None


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


def test_tool_output_is_redacted_before_history_and_audit(monkeypatch):
    """S5 (ADR-0011): a secret in tool output never reaches the message history
    or the recorded `ToolCall`, the count lands on the result, and one
    `redaction` event is emitted."""
    monkeypatch.setattr(
        diag, "run_tool", lambda *a: ("db down: postgresql://svc:p4ss@10.9.9.9:5432/pmt", False)
    )
    events: list = []
    turns = [
        ("tool_use", [_tool_block("search_logs", {"query": "redis"})]),
        ("end_turn", [_text_block("done")]),
    ]
    result = _run(
        monkeypatch,
        turns=turns,
        diagnosis=_diagnosis("Roll back the implicated deploy"),
        on_event=events.append,
    )

    tc = result.tool_calls[0]
    assert "postgresql://svc:p4ss@10.9.9.9:5432/pmt" not in tc.result_json
    assert "[redacted:connection-string]" in tc.result_json
    assert result.redaction_count == 1

    redaction_events = [e for e in events if e["type"] == "redaction"]
    assert len(redaction_events) == 1
    assert redaction_events[0]["data"]["count"] == 1
    assert redaction_events[0]["data"]["kinds"] == {"connection-string": 1}


def test_clean_tool_output_emits_no_redaction_event(monkeypatch):
    turns = [
        ("tool_use", [_tool_block("query_metrics", {"metric": "paymentsvc_db_pool_checked_out"})]),
        ("end_turn", [_text_block("pinned at size")]),
    ]
    events: list = []
    result = _run(
        monkeypatch,
        turns=turns,
        diagnosis=_diagnosis("Roll back the implicated deploy"),
        on_event=events.append,
    )
    assert result.redaction_count == 0
    assert not [e for e in events if e["type"] == "redaction"]


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


def test_synthesis_returning_none_escalates_without_crashing(monkeypatch):
    # llm.parse can hand back parsed_output=None (a refusal, a truncation). The
    # loop must escalate on the tool evidence, not raise.
    turns = [("end_turn", [_text_block("looked around")])]
    result = _run(monkeypatch, turns=turns, diagnosis=None)

    assert result.diagnosis is None
    assert result.disposition == "escalate"
    assert result.escalate
    assert not result.short_circuited  # distinct from a triage short-circuit
    assert not result.grounded
    assert result.guardrail is None


def test_synthesis_none_on_the_grounding_retry_also_escalates(monkeypatch):
    turns = [("end_turn", [_text_block("done")])]
    result = _run(
        monkeypatch,
        turns=turns,
        diagnosis=[_diagnosis("Reboot the universe and hope for the best"), None],
    )

    assert result.diagnosis is None
    assert result.disposition == "escalate"
    assert not result.short_circuited


def test_cache_disabled_by_default_makes_no_cache_calls(monkeypatch):
    """`use_cache` defaults False — the eval suite and red-team harness rely on
    this to always exercise the full triage + retrieval path."""
    seen = {"embed": 0, "lookup": 0}
    monkeypatch.setattr(
        diag, "embed_query", lambda *a, **k: seen.__setitem__("embed", seen["embed"] + 1) or [0.0]
    )
    monkeypatch.setattr(
        diag.alert_cache, "lookup", lambda *a, **k: seen.__setitem__("lookup", seen["lookup"] + 1)
    )

    turns = [("end_turn", [_text_block("checked")])]
    result = _run(monkeypatch, turns=turns, diagnosis=_readonly_diagnosis())  # use_cache=False

    assert not result.cache_hit
    assert seen == {"embed": 0, "lookup": 0}


def test_cache_hit_skips_triage_and_retrieval(monkeypatch):
    from runbook.core.cache import CacheHit

    hit = CacheHit(
        entry_id=7,
        similarity=0.991,
        age_s=120.0,
        triage=_triage("known-runbook"),
        retrieved=[_chunk()],
    )
    triage_calls = {"n": 0}

    async def boom_triage(*a, **k):  # must not be called
        triage_calls["n"] += 1
        raise AssertionError("triage ran on a cache hit")

    monkeypatch.setattr(diag, "triage", boom_triage)
    monkeypatch.setattr(
        diag,
        "retrieve",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("retrieve ran on a cache hit")),
    )

    events: list = []
    turns = [("end_turn", [_text_block("done")])]
    result = _run(
        monkeypatch,
        turns=turns,
        diagnosis=_diagnosis("Roll back the implicated deploy"),
        use_cache=True,
        cache_hit=hit,
        on_event=events.append,
    )

    assert result.cache_hit
    assert triage_calls["n"] == 0
    assert result.triage.category == "known-runbook"
    assert result.diagnosis is not None  # the loop still ran fresh
    assert result.disposition == "needs-approval"
    cache_events = [e for e in events if e["type"] == "cache.hit"]
    assert len(cache_events) == 1
    assert cache_events[0]["data"]["similarity"] == 0.991


def test_cache_miss_stores_the_prefix(monkeypatch):
    sink: list = []
    turns = [("end_turn", [_text_block("done")])]
    result = _run(
        monkeypatch,
        turns=turns,
        diagnosis=_diagnosis("Roll back the implicated deploy"),
        use_cache=True,
        cache_hit=None,
        store_sink=sink,
    )

    assert not result.cache_hit
    assert len(sink) == 1
    assert sink[0]["triage"].category == "known-runbook"
    assert [c.title for c in sink[0]["retrieved"]] == [_chunk().title]


def test_cache_not_stored_on_a_short_circuit(monkeypatch):
    sink: list = []
    turns = [("end_turn", [_text_block("nope")])]
    _run(
        monkeypatch,
        turns=turns,
        diagnosis=_diagnosis("Roll back the implicated deploy"),
        triage=_triage("noise-or-flapping"),
        use_cache=True,
        store_sink=sink,
    )
    assert sink == []


@pytest.mark.parametrize(
    "category, confidence, expect_fast",
    [
        ("known-runbook", "high", True),
        ("known-runbook", "medium", False),
        ("known-runbook", "low", False),
        ("novel-incident", "high", False),
    ],
)
def test_route_loop_model_picks_fast_chain_only_for_confident_known(
    category, confidence, expect_fast
):
    from runbook.config import get_settings

    s = get_settings()
    tri = diag.TriageResult(category=category, rationale="x", confidence=confidence)
    model, fallbacks = diag._route_loop_model(tri, s)
    if expect_fast:
        assert model == s.fast_loop_model and fallbacks == s.fast_loop_fallbacks
    else:
        assert model == s.diagnosis_model and fallbacks == s.loop_fallbacks


def test_by_model_accounting_splits_tokens_across_models(monkeypatch):
    """Cost attribution: tool-loop tokens (fake run_turn, no model echoed → keyed
    to the routed model) are tracked apart from synthesis + second-pass tokens
    (fake parse model), and the per-model totals reconcile with the flat total."""
    from runbook.config import get_settings

    turns = [("end_turn", [_text_block("done")])]
    result = _run(monkeypatch, turns=turns, diagnosis=_readonly_diagnosis())

    by = result.usage["by_model"]
    routed = get_settings().fast_loop_model  # known-runbook + high confidence
    assert by[routed] == {"input_tokens": 10, "output_tokens": 5}  # one loop turn
    assert by["fake/parse-model"]["input_tokens"] == 100 + 15  # synthesis + 2nd pass
    assert sum(m["input_tokens"] for m in by.values()) == result.usage["input_tokens"]
    assert sum(m["output_tokens"] for m in by.values()) == result.usage["output_tokens"]


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
