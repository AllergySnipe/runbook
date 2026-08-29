"""The diagnosis loop: triage → retrieve runbook → tool-use investigation →
grounded structured diagnosis.

Explicit and manual on purpose (ADR-0001, ADR-0005): the SDK's tool-runner is
beta and hides the loop, and the loop is where the safety branches live. First
branch now in place: **triage** (`core/triage.py`) runs before retrieval —
`noise-or-flapping` / `need-more-info` short-circuit with no diagnosis; a
`novel-incident` proceeds but tells the model retrieval is low-prior. The
approval gate (S1), the tool allowlist enforcement path (S2, already in
`tools.run_tool`), the guardrail second pass, redaction (S5), and tracing are
still Week 2.

Grounding (S3): after synthesis we check every remediation step quotes a line
that actually appears in the retrieved runbook. This slice *flags* violations;
the "regenerate once, then downgrade to escalate" enforcement is Week 2.
"""

from __future__ import annotations

import asyncio
import re
import time
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
from .triage import TriageResult, triage

MAX_ITERS = 8


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
        `need-more-info`). No diagnosis was produced."""
        return self.diagnosis is None

    @property
    def grounded(self) -> bool:
        """A proposal with steps, all of which cite a real runbook line. No steps
        means "escalate to a human" — not grounded, but not a failure either."""
        if self.diagnosis is None:
            return False
        return bool(self.diagnosis.remediation_steps) and not self.grounding_issues

    @property
    def escalate(self) -> bool:
        return self.diagnosis is not None and not self.diagnosis.remediation_steps


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


def _tool_results_for(blocks: list, scenario: str, sink: list[ToolCall]) -> list[dict]:
    results = []
    for block in blocks:
        if block.type != "tool_use":
            continue
        payload, is_error = run_tool(block.name, scenario, dict(block.input))
        sink.append(ToolCall(block.name, dict(block.input), payload, is_error))
        results.append(
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": payload,
                "is_error": is_error,
            }
        )
    return results


async def diagnose(
    alert: str,
    scenario_name: str,
    *,
    k: int = 4,
    max_iters: int = MAX_ITERS,
) -> DiagnoseResult:
    """Run the loop for one alert against one sim scenario."""
    started = time.monotonic()
    settings = get_settings()
    model = settings.diagnosis_model

    load_scenario(scenario_name)  # fail early on a bad scenario name

    tri = await triage(alert)
    if not tri.proceed:
        # `noise-or-flapping` / `need-more-info` — don't spend a tool-loop.
        return DiagnoseResult(
            alert=alert,
            scenario=scenario_name,
            triage=tri,
            diagnosis=None,
            retrieved=[],
            tool_calls=[],
            iterations=0,
            hit_max_iters=False,
            grounding_issues=[],
            usage={"input_tokens": 0, "output_tokens": 0},
            elapsed_s=round(time.monotonic() - started, 1),
        )

    retrieved = await asyncio.to_thread(retrieve, alert, k)
    if not retrieved:
        raise RuntimeError("retrieval returned nothing for this alert")

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
        resp = await llm.run_turn(messages, model=model, system=system, tools=SCHEMAS)
        usage["input_tokens"] += resp.usage.input_tokens
        usage["output_tokens"] += resp.usage.output_tokens
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "tool_use":
            if iterations >= max_iters:
                hit_max = True
                # answer the pending tool calls so history stays valid, then stop
                messages.append(
                    {
                        "role": "user",
                        "content": _tool_results_for(resp.content, scenario_name, tool_calls),
                    }
                )
                break
            results = await asyncio.to_thread(
                _tool_results_for, resp.content, scenario_name, tool_calls
            )
            messages.append({"role": "user", "content": results})
            continue

        if resp.stop_reason == "pause_turn":
            continue  # re-send; server-tool artifact (we have none, but be safe)

        break  # end_turn, max_tokens, refusal — move to synthesis with what we have

    messages.append(
        {
            "role": "user",
            "content": load_prompt(
                "synthesize", runbook_source=runbook_source, runbook_text=runbook_text
            ),
        }
    )
    diagnosis, syn_usage = await llm.parse(
        messages, model=model, system=system, schema=Diagnosis, tools=SCHEMAS
    )
    usage["input_tokens"] += syn_usage.input_tokens
    usage["output_tokens"] += syn_usage.output_tokens

    return DiagnoseResult(
        alert=alert,
        scenario=scenario_name,
        triage=tri,
        diagnosis=diagnosis,
        retrieved=retrieved,
        tool_calls=tool_calls,
        iterations=iterations,
        hit_max_iters=hit_max,
        grounding_issues=_check_grounding(diagnosis, runbook_text),
        usage=usage,
        elapsed_s=round(time.monotonic() - started, 1),
    )
