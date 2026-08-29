"""The guardrail layer: code that runs *after* the diagnosis model and can
override it. Safety is enforced here, never requested in a prompt (CLAUDE.md
golden rule 5).

Two checks live here:

- **Action classification (S1 groundwork).** Each proposed remediation step is
  classified `read-only` vs `state-changing` *independently* of the model's own
  `state_changing` self-report — the model that might be wrong about the fix is
  not trusted to say whether the fix is dangerous. Primary signal is
  deterministic (the runbook's own `[read-only]` / `[state-changing …]` tag, plus
  a verb scan of the action text); anything not positively read-only defaults to
  `state-changing` (fail-safe). A cheap second-model pass (`second_pass`) can
  only *tighten* — upgrade a step or raise a concern — never downgrade.

- **Grounding enforcement (S3)** lives in `core/loop.py` (it needs the message
  history to regenerate), but the disposition it feeds into is computed here.

The loop turns the report into a `disposition`: `auto` (all steps read-only and
grounded), `needs-approval` (≥1 state-changing step), or `escalate` (no grounded
step survived). The actual pending-approval gate — the DB row a human resolves —
is the next slice.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .. import llm
from ..prompts import load as load_prompt

ActionClass = Literal["read-only", "state-changing"]


class _Step(Protocol):
    action: str
    runbook_quote: str
    state_changing: bool


def _normalise(text: str) -> str:
    """Fold everything that isn't a letter or digit to a single space — same
    normalisation the grounding check uses, so a quote matches the runbook line
    it came from regardless of markdown, source line wraps, or the dropped tag."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


# High-precision state-changing verbs: words that are almost never nouns and
# almost always mean "do a mutating thing". They exist to (a) override a
# read-only verb when a real mutation co-occurs ("compare … then roll back") and
# (b) give a specific reason string. Anything genuinely state-changing that these
# miss ("raise the pool size", "set the flag") still lands as state-changing via
# the fail-safe default below — just with a less specific reason. Kept tight on
# purpose: broad noun-ish verbs (deploy, update, change, increase) caused false
# positives on read-only steps that merely mention "the deploy" / "a status
# update".
_STATE_CHANGING = re.compile(
    r"\b(?:"
    r"roll\s?back|rolled\s?back|redeploy|re-?deploy|revert|roll\s?forward|hotfix|"
    r"restart|reboot|bounce|recycle|"
    r"scale\s+(?:out|up|down|in)|add\s+(?:more\s+)?pods?|remove\s+pods?|autoscal|"
    r"fail\s?over|switch\s?over|cut\s?over|promote|demote|"
    r"delete|drop\s+the|truncate|purge|evict|prune|"
    r"disable|enable|turn\s+off|turn\s+on|"
    r"kill|terminate|drain|cordon|uncordon|quarantine|"
    r"clear\s+(?:the\s+)?cache|invalidate|reindex|rebuild\s+the|"
    r"rotate|"
    r"unblock|throttle|"
    r"revoke|grant"
    r")\b",
    re.IGNORECASE,
)

# Verbs that only observe / communicate.
_READ_ONLY = re.compile(
    r"\b(?:"
    r"confirm|check|verify|validate|inspect|examine|review|look|observe|monitor|watch|"
    r"identify|determine|assess|evaluate|measure|gather|collect|correlate|compare|diff|"
    r"page|escalate|notify|alert|contact|inform|tell|ask|loop\s+in|hand\s+off|"
    r"document|note|record|capture|"
    r"query|search|grep|read|list|describe|show|view|pull|fetch|trace"
    r")\b",
    re.IGNORECASE,
)

# "file / open / raise a follow-up ticket" — a read-only bookkeeping action even
# though the verbs otherwise look active.
_FILE_TICKET = re.compile(
    r"\b(?:file|open|create|raise|log)\b.{0,40}"
    r"\b(?:ticket|issue|follow.?up|bug|task|jira|card|postmortem|post-mortem)\b"
    r"|\b(?:ticket|issue|follow.?up|bug|task|jira|card)\b.{0,20}\b(?:file[d]?|open|creat|rais|log)",
    re.IGNORECASE,
)


@dataclass
class ActionVerdict:
    step_index: int
    action: str
    classification: ActionClass
    reason: str
    model_flag: bool
    model_disagreed: bool  # model said read-only, guardrail says state-changing (or vice versa)
    upgraded_by_second_pass: bool = False


def _runbook_tag(quote: str, runbook_text: str) -> ActionClass | None:
    """The `[read-only]` / `[state-changing …]` tag the runbook author put on the
    bullet this quote came from, or `None` if the quote can't be located or the
    bullet is untagged. Works on normalised text so it survives the model
    dropping the tag from the quote and source line wraps."""
    corpus = _normalise(runbook_text)
    frag = _normalise(quote)[:55]
    if not frag:
        return None
    pos = corpus.find(frag)
    if pos == -1:
        return None
    preceding = corpus[max(0, pos - 60) : pos]
    if "state changing" in preceding:
        return "state-changing"
    if "read only" in preceding:
        return "read-only"
    return None


def classify_action(
    action: str, runbook_quote: str, model_flag: bool, runbook_text: str = ""
) -> ActionVerdict:
    """Classify one step, not trusting `model_flag`."""
    tag = _runbook_tag(runbook_quote, runbook_text) if runbook_text else None
    files_ticket = bool(_FILE_TICKET.search(action))
    sc_verb = bool(_STATE_CHANGING.search(action)) and not files_ticket
    ro_verb = bool(_READ_ONLY.search(action)) or files_ticket

    if tag == "state-changing":
        cls: ActionClass = "state-changing"
        reason = "runbook tags this step [state-changing — needs approval]"
    elif sc_verb:
        cls = "state-changing"
        reason = "action contains a state-changing verb" + (
            "; runbook tags it [read-only] — disagreement, taking the safe reading"
            if tag == "read-only"
            else ""
        )
    elif tag == "read-only":
        cls = "read-only"
        reason = "runbook tags this step [read-only] and the action has no state-changing verb"
    elif ro_verb:
        cls = "read-only"
        reason = "action is observational (read-only verb, no state-changing verb)"
    else:
        cls = "state-changing"
        reason = (
            "could not positively classify as read-only — defaulting to state-changing (fail-safe)"
        )

    model_disagreed = model_flag != (cls == "state-changing")
    return ActionVerdict(
        step_index=-1,
        action=action,
        classification=cls,
        reason=reason,
        model_flag=model_flag,
        model_disagreed=model_disagreed,
    )


def classify_steps(steps: list[_Step], runbook_text: str = "") -> list[ActionVerdict]:
    verdicts: list[ActionVerdict] = []
    for i, step in enumerate(steps):
        v = classify_action(step.action, step.runbook_quote, step.state_changing, runbook_text)
        v.step_index = i
        verdicts.append(v)
    return verdicts


# --- the second-model pass (Haiku) --------------------------------------------


class SecondPassConcern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_index: int
    kind: Literal["should-be-state-changing", "not-supported-by-runbook", "other"]
    detail: str = Field(description="one sentence")


class SecondPassReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concerns: list[SecondPassConcern]


async def second_pass(
    steps: list[_Step], runbook_text: str, *, model: str, fallbacks: Sequence[str] = ()
) -> tuple[list[SecondPassConcern], object | None]:
    """A fresh, cheap model looks only at the final proposal + the runbook and
    flags: steps it thinks change state, and steps not supported by the runbook.
    Advisory — the caller may upgrade a step but never downgrades one.

    Returns `(concerns, usage)`; `usage` is `None` when no call was made."""
    if not steps:
        return [], None
    numbered = "\n".join(
        f"{i}. {s.action}\n   quoted runbook line: {s.runbook_quote}" for i, s in enumerate(steps)
    )
    system = load_prompt("guardrail")
    messages = [
        {
            "role": "user",
            "content": (
                f"Proposed remediation steps:\n\n{numbered}\n\n"
                f"<runbook>\n{runbook_text}\n</runbook>\n\n"
                "Report concerns per the rules. Empty list if every step is clearly "
                "read-only and clearly supported by the runbook."
            ),
        }
    ]
    report, usage = await llm.parse(
        messages, model=model, system=system, schema=SecondPassReport, fallbacks=fallbacks
    )
    return report.concerns, usage


def apply_second_pass(verdicts: list[ActionVerdict], concerns: list[SecondPassConcern]) -> None:
    """Tighten-only: a `should-be-state-changing` concern upgrades that step.
    Nothing here can make a step read-only."""
    by_index = {v.step_index: v for v in verdicts}
    for c in concerns:
        if c.kind == "should-be-state-changing":
            v = by_index.get(c.step_index)
            if v and v.classification != "state-changing":
                v.classification = "state-changing"
                v.reason = f"{v.reason}; second-pass upgraded: {c.detail}"
                v.upgraded_by_second_pass = True
                v.model_disagreed = not v.model_flag  # model said read-only, now state-changing


@dataclass
class GuardrailReport:
    verdicts: list[ActionVerdict]
    second_pass_concerns: list[SecondPassConcern] = field(default_factory=list)
    regenerated_for_grounding: bool = False
    dropped_ungrounded: int = 0
    second_pass_ran: bool = False

    @property
    def any_state_changing(self) -> bool:
        return any(v.classification == "state-changing" for v in self.verdicts)

    @property
    def disagreements(self) -> list[ActionVerdict]:
        return [v for v in self.verdicts if v.model_disagreed]

    @property
    def unsupported_concerns(self) -> list[SecondPassConcern]:
        return [c for c in self.second_pass_concerns if c.kind == "not-supported-by-runbook"]
