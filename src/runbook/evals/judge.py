"""LLM-as-judge for diagnosis root-cause quality.

There is no string to match a root cause against, so a separate model call grades
it. **Reference-based**: the judge compares the candidate to a hand-written
correct answer (`EvalCase.reference_root_cause`) — far more reliable than asking
"is this good?" in a vacuum.

Known judge failure modes and the mitigations here (ADR-0008 / ADR-0009):

- *self-preference* — the judge runs on `settings.judge_model`, deliberately a
  different model family from `diagnosis_model` (MiniMax judging GLM), plus the
  reference answer + a concrete rubric, and spot-checking rationales each run.
- *verbosity / leniency bias* — the prompt forces the judge to enumerate
  `missing` and `hallucinated` *before* scoring, and to floor the score when the
  subsystem is wrong.
- *judge non-determinism* — it adds noise; the report treats the mean over the
  set, not any single case, as the signal, and the baseline gate has a tolerance.

The judge prompt is a versioned file (`prompts/eval_judge.md`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .. import llm
from ..config import get_settings
from ..prompts import load as load_prompt
from .cases import EvalCase


class JudgeVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # enumeration first — the judge does the comparison work before it commits to a score
    missing: list[str] = Field(description="facts in the reference the candidate omits")
    hallucinated: list[str] = Field(description="candidate claims unsupported by the reference")
    names_correct_subsystem: bool = Field(
        description="candidate points at the same component / mechanism as the reference"
    )
    score: Literal[1, 2, 3, 4, 5]
    rationale: str = Field(description="one or two sentences")


def _candidate_text(diagnosis) -> str:
    ev = "\n".join(f"  - {e}" for e in diagnosis.evidence) or "  (none)"
    return (
        f"failure_mode: {diagnosis.failure_mode}\n"
        f"confidence: {diagnosis.confidence}\n"
        f"root_cause: {diagnosis.root_cause}\n"
        f"summary: {diagnosis.summary}\n"
        f"evidence:\n{ev}"
    )


async def judge(case: EvalCase, result, *, model: str | None = None):
    """Grade one diagnosis against its reference. Returns `(JudgeVerdict, usage)`.

    Caller must ensure `result.diagnosis is not None`."""
    settings = get_settings()
    model = model or settings.judge_model
    system = load_prompt("eval_judge")
    messages = [
        {
            "role": "user",
            "content": (
                f"<reference_root_cause>\n{case.reference_root_cause}\n</reference_root_cause>\n\n"
                f"<candidate_diagnosis>\n{_candidate_text(result.diagnosis)}\n</candidate_diagnosis>\n\n"
                "Grade the candidate per the method and rubric."
            ),
        }
    ]
    verdict, usage = await llm.parse(
        messages,
        model=model,
        system=system,
        schema=JudgeVerdict,
        fallbacks=settings.judge_fallbacks,
        trace_name="eval-judge",
    )
    return verdict, usage
