"""The diagnosis loop: triage → retrieve → tool-use investigation → synthesis →
grounding enforcement → guardrail → disposition.

Explicit and manual on purpose (ADR-0001, ADR-0005): a framework's agentic
tool-runner hides the loop, and the loop is where the safety branches live.
Provider is OpenRouter via `llm.py` (ADR-0009) — this module stays provider-neutral
(`llm.Turn` / `llm.ToolRequest`).

Safety branches now in place:
- **Triage** (`core/triage.py`) runs before retrieval — `noise-or-flapping` /
  `need-more-info` short-circuit with no diagnosis; `novel-incident` proceeds but
  tells the model retrieval is low-prior.
- **Grounding enforcement (S3)** — every remediation step must quote a line that
  appears in the runbook. Ungrounded ⇒ regenerate synthesis once; still
  ungrounded ⇒ drop those steps; nothing left ⇒ escalate.
- **Guardrail (`core/guardrail.py`)** — each surviving step is classified
  read-only vs state-changing independently of the model's self-report, then a
  cheap second-model pass can only tighten. The run gets a `disposition`:
  `auto` / `needs-approval` / `escalate`.

`diagnose()` returns a `DiagnoseResult` and touches no DB — the CLI persists it
(the S1 approval gate + S6 audit record, `core/store.py`). Still to come:
redaction (S5), tracing.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .. import llm
from ..config import get_settings
from ..prompts import load as load_prompt
from ..rag import RetrievedChunk, retrieve
from ..sim import load_scenario
from ..tools import SCHEMAS, run_tool
from . import events as ev
from .events import Event
from .guardrail import GuardrailReport, apply_second_pass, classify_steps, second_pass
from .triage import TriageResult, triage

MAX_ITERS = 8

Disposition = Literal["auto", "needs-approval", "escalate"]


class RemediationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(description="the remediation action, imperative")
    runbook_quote: str = Field(
        description="verbatim line from the runbook this step is grounded in"
    )
    state_changing: bool = Field(description="true if it changes system state (needs approval)")


class Diagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    root_cause: str
    failure_mode: str = Field(description="the runbook's failure_mode value, or 'unknown'")
    confidence: Literal["low", "medium", "high"]
    evidence: list[str] = Field(description="concrete tool findings supporting the root cause")
    remediation_steps: list[RemediationStep]


@dataclass
class ToolCall:
    name: str
    input: dict
    result_json: str
    is_error: bool


@dataclass
class GroundingIssue:
    step_index: int
    quote: str
    reason: str


@dataclass
class DiagnoseResult:
    alert: str
    scenario: str
    triage: TriageResult
    diagnosis: Diagnosis | None
    guardrail: GuardrailReport | None
    disposition: Disposition | None
    retrieved: list[RetrievedChunk]
    tool_calls: list[ToolCall]
    iterations: int
    hit_max_iters: bool
    grounding_issues: list[GroundingIssue]
    usage: dict[str, int]
    elapsed_s: float

    @property
    def short_circuited(self) -> bool:
        """Triage routed this to a non-loop lane (`noise-or-flapping` /
        `need-more-info`). No diagnosis was produced and no disposition set.

        Distinct from a synthesis failure, which also has `diagnosis is None` but
        carries `disposition == "escalate"`."""
        return self.diagnosis is None and self.disposition is None

    @property
    def grounded(self) -> bool:
        """A proposal with steps, all of which cite a real runbook line."""
        if self.diagnosis is None:
            return False
        return bool(self.diagnosis.remediation_steps) and not self.grounding_issues

    @property
    def escalate(self) -> bool:
        return self.disposition == "escalate"

    @property
    def needs_approval(self) -> bool:
        return self.disposition == "needs-approval"


_REPO_ROOT = Path(__file__).resolve().parents[3]


def _normalise(text: str) -> str:
    """Loose normalisation for provenance matching: fold everything that isn't a
    letter or digit to a single space. Survives the model reformatting a runbook
    bullet — dropping the `[state-changing]` tag, the `**bold**` markers, wrapped
    whitespace, `—` vs `--`. We're verifying the quote *came from* the runbook,
    not that it was copied byte-for-byte."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


_GROUND_FRAGMENT_LEN = 55  # ~10 words of a normalised quote must match contiguously


def _full_doc(chunk: RetrievedChunk) -> str | None:
    """The whole source file, if it's on disk (the synthetic runbooks are).

    Retrieval returns whichever *chunks* match the alert's symptoms — often the
    Summary/Diagnosis sections, not Remediation. Grounded remediation needs the
    Remediation section in context, so we hydrate the full runbook for the top hit.
    """
    if not chunk.path:
        return None
    path = _REPO_ROOT / chunk.path
    return path.read_text() if path.is_file() else None


def _assemble_runbook(chunks: list[RetrievedChunk]) -> tuple[str, str]:
    """Returns `(runbook_text, source_label)` for the prompt + the grounding check."""
    top = chunks[0]
    source = top.path or top.source
    full = _full_doc(top)
    blocks = [f"=== PRIMARY RUNBOOK: {top.title} ({source}) ===\n{full or top.chunk_text}"]
    seen = {source}
    for c in chunks[1:]:
        label = c.path or c.title
        if label in seen:
            continue
        seen.add(label)
        blocks.append(f"--- related: {c.title} › {c.heading_display} ({label}) ---\n{c.chunk_text}")
    return "\n\n".join(blocks), source


def _check_grounding(diagnosis: Diagnosis, runbook_text: str) -> list[GroundingIssue]:
    corpus = _normalise(runbook_text)
    issues: list[GroundingIssue] = []
    for i, step in enumerate(diagnosis.remediation_steps):
        quote = step.runbook_quote.strip()
        if not quote:
            issues.append(GroundingIssue(i, quote, "no runbook_quote given"))
            continue
        # require a solid contiguous fragment of the normalised quote to appear
        fragment = _normalise(quote)[:_GROUND_FRAGMENT_LEN]
        if fragment and fragment not in corpus:
            issues.append(GroundingIssue(i, quote, "quote not found in retrieved runbook"))
    return issues


def _emit_tool_calls(emit: Callable[[Event], None], sink: list[ToolCall], since: int) -> None:
    """Narrate each tool call recorded since index `since`. Called from the main
    coroutine (not the worker thread) so `emit` stays on the event loop."""
    for tc in sink[since:]:
        emit(ev.event(ev.TOOL_CALL, name=tc.name, input=tc.input, is_error=tc.is_error))


def _tool_results_for(
    requests: list[llm.ToolRequest], scenario: str, sink: list[ToolCall]
) -> list[dict]:
    """Execute each requested tool, record it in `sink`, and return one
    OpenAI-shape `tool` message per call (to append to the message history)."""
    messages = []
    for req in requests:
        args = dict(req.arguments)
        payload, is_error = run_tool(req.name, scenario, args)
        sink.append(ToolCall(req.name, args, payload, is_error))
        messages.append({"role": "tool", "tool_call_id": req.id, "content": payload})
    return messages


async def diagnose(
    alert: str,
    scenario_name: str,
    *,
    k: int = 4,
    max_iters: int = MAX_ITERS,
    on_event: Callable[[Event], None] | None = None,
) -> DiagnoseResult:
    """Run the loop for one alert against one sim scenario.

    `on_event`, if given, is called synchronously at each milestone (see
    `core/events.py`) — the dashboard uses it to stream a live timeline. It is
    pure narration: the return value is unaffected, and `on_event=None` (the CLI
    and the eval runner) is a behaviourless no-op.
    """
    started = time.monotonic()
    settings = get_settings()
    model = settings.diagnosis_model
    loop_fallbacks = settings.loop_fallbacks
    structured_fallbacks = settings.structured_fallbacks

    emit: Callable[[Event], None] = on_event or (lambda _e: None)

    load_scenario(scenario_name)  # fail early on a bad scenario name

    emit(ev.event(ev.TRIAGE_START))
    tri = await triage(alert)
    emit(
        ev.event(
            ev.TRIAGE_DONE,
            category=tri.category,
            confidence=tri.confidence,
            proceed=tri.proceed,
            low_prior=tri.low_prior,
        )
    )
    if not tri.proceed:
        emit(ev.event(ev.SHORT_CIRCUIT, category=tri.category))
        # `noise-or-flapping` / `need-more-info` — don't spend a tool-loop.
        return DiagnoseResult(
            alert=alert,
            scenario=scenario_name,
            triage=tri,
            diagnosis=None,
            guardrail=None,
            disposition=None,
            retrieved=[],
            tool_calls=[],
            iterations=0,
            hit_max_iters=False,
            grounding_issues=[],
            usage={"input_tokens": 0, "output_tokens": 0},
            elapsed_s=round(time.monotonic() - started, 1),
        )

    emit(ev.event(ev.RETRIEVE_START))
    retrieved = await asyncio.to_thread(retrieve, alert, k)
    if not retrieved:
        raise RuntimeError("retrieval returned nothing for this alert")
    emit(
        ev.event(
            ev.RETRIEVE_DONE,
            docs=list(dict.fromkeys((c.path or c.source) for c in retrieved)),
        )
    )

    runbook_text, runbook_source = _assemble_runbook(retrieved)
    system = load_prompt("diagnose", runbook_source=runbook_source, runbook_text=runbook_text)

    low_prior_note = (
        "\n\nNote: triage classified this as a *novel incident* — no runbook is "
        "known to cover it. The retrieved runbook may be only loosely relevant; "
        "weight your live tool evidence over it, and prefer escalation if the "
        "evidence does not clearly fit."
        if tri.low_prior
        else ""
    )
    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                f"Alert on `paymentsvc` (sim scenario `{scenario_name}`):\n\n{alert}\n\n"
                "Investigate per the runbook and report what you find."
                f"{low_prior_note}"
            ),
        }
    ]

    tool_calls: list[ToolCall] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    iterations = 0
    hit_max = False

    while True:
        iterations += 1
        turn = await llm.run_turn(
            messages, model=model, system=system, tools=SCHEMAS, fallbacks=loop_fallbacks
        )
        usage["input_tokens"] += turn.usage.input_tokens
        usage["output_tokens"] += turn.usage.output_tokens
        messages.append(turn.assistant_message)

        if turn.stop_reason == "tool_calls" and turn.tool_requests:
            before = len(tool_calls)
            if iterations >= max_iters:
                hit_max = True
                # answer the pending tool calls so history stays valid, then stop
                messages.extend(_tool_results_for(turn.tool_requests, scenario_name, tool_calls))
                _emit_tool_calls(emit, tool_calls, before)
                break
            results = await asyncio.to_thread(
                _tool_results_for, turn.tool_requests, scenario_name, tool_calls
            )
            messages.extend(results)
            _emit_tool_calls(emit, tool_calls, before)
            continue

        break  # stop / length / other — move to synthesis with what we have

    def _account(u) -> None:
        usage["input_tokens"] += u.input_tokens
        usage["output_tokens"] += u.output_tokens

    def _synthesis_failed() -> DiagnoseResult:
        """The synthesis call produced no parseable structured output (a refusal,
        a truncation, an unparseable response). Don't crash mid-incident — hand
        the tool evidence to a human. `diagnosis is None` + `disposition ==
        'escalate'` distinguishes this from a triage short-circuit."""
        emit(ev.event(ev.DISPOSITION, disposition="escalate"))
        return DiagnoseResult(
            alert=alert,
            scenario=scenario_name,
            triage=tri,
            diagnosis=None,
            guardrail=None,
            disposition="escalate",
            retrieved=retrieved,
            tool_calls=tool_calls,
            iterations=iterations,
            hit_max_iters=hit_max,
            grounding_issues=[],
            usage=usage,
            elapsed_s=round(time.monotonic() - started, 1),
        )

    async def _synthesize(extra: str | None = None) -> Diagnosis | None:
        msgs = [*messages]
        if extra is None:
            msgs.append(
                {
                    "role": "user",
                    "content": load_prompt(
                        "synthesize", runbook_source=runbook_source, runbook_text=runbook_text
                    ),
                }
            )
        else:
            msgs.append({"role": "user", "content": extra})
        try:
            d, u = await llm.parse(
                msgs, model=model, system=system, schema=Diagnosis, fallbacks=structured_fallbacks
            )
        except llm.LLMParseError:
            return None
        _account(u)
        return d

    # --- synthesis + grounding enforcement (S3) ---------------------------
    emit(ev.event(ev.SYNTHESIS_START))
    diagnosis = await _synthesize()
    if diagnosis is None:
        return _synthesis_failed()
    emit(
        ev.event(
            ev.SYNTHESIS_DONE,
            confidence=diagnosis.confidence,
            failure_mode=diagnosis.failure_mode,
            n_steps=len(diagnosis.remediation_steps),
        )
    )
    grounding_issues = _check_grounding(diagnosis, runbook_text)
    regenerated = False
    dropped = 0
    if grounding_issues:
        regenerated = True
        emit(ev.event(ev.GROUNDING_REGENERATED, issues=len(grounding_issues)))
        detail = "; ".join(f"step {g.step_index + 1} — {g.reason}" for g in grounding_issues)
        regen = await _synthesize(
            "Your remediation steps failed the grounding check: "
            f"{detail}. Every remediation step's `runbook_quote` must be a phrase that "
            "appears verbatim in the runbook above. Produce the full structured diagnosis "
            "again: for each step either set `runbook_quote` to a verbatim runbook phrase, "
            "or omit that step entirely."
        )
        if regen is None:
            return _synthesis_failed()
        diagnosis = regen
        grounding_issues = _check_grounding(diagnosis, runbook_text)
        if grounding_issues:
            bad = {g.step_index for g in grounding_issues}
            kept = [s for i, s in enumerate(diagnosis.remediation_steps) if i not in bad]
            dropped = len(diagnosis.remediation_steps) - len(kept)
            diagnosis.remediation_steps = kept
            grounding_issues = []
            emit(ev.event(ev.GROUNDING_DROPPED, count=dropped))

    # --- guardrail: independent action classification + second pass ------
    emit(ev.event(ev.GUARDRAIL_START))
    verdicts = classify_steps(diagnosis.remediation_steps, runbook_text)
    concerns = []
    second_pass_ran = False
    if diagnosis.remediation_steps:
        second_pass_ran = True
        concerns, sp_usage = await second_pass(
            diagnosis.remediation_steps,
            runbook_text,
            model=settings.triage_model,
            fallbacks=structured_fallbacks,
        )
        if sp_usage is not None:
            _account(sp_usage)
        apply_second_pass(verdicts, concerns)
    guardrail = GuardrailReport(
        verdicts=verdicts,
        second_pass_concerns=concerns,
        regenerated_for_grounding=regenerated,
        dropped_ungrounded=dropped,
        second_pass_ran=second_pass_ran,
    )
    emit(
        ev.event(
            ev.GUARDRAIL_DONE,
            verdicts=[
                {
                    "step_index": v.step_index,
                    "classification": v.classification,
                    "model_disagreed": v.model_disagreed,
                }
                for v in verdicts
            ],
            concerns=[
                {"step_index": c.step_index, "kind": c.kind, "detail": c.detail} for c in concerns
            ],
        )
    )

    if not diagnosis.remediation_steps:
        disposition: Disposition = "escalate"
    elif guardrail.any_state_changing:
        disposition = "needs-approval"
    else:
        disposition = "auto"
    emit(ev.event(ev.DISPOSITION, disposition=disposition))

    return DiagnoseResult(
        alert=alert,
        scenario=scenario_name,
        triage=tri,
        diagnosis=diagnosis,
        guardrail=guardrail,
        disposition=disposition,
        retrieved=retrieved,
        tool_calls=tool_calls,
        iterations=iterations,
        hit_max_iters=hit_max,
        grounding_issues=grounding_issues,
        usage=usage,
        elapsed_s=round(time.monotonic() - started, 1),
    )
