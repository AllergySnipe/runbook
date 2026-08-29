"""The runner: for each golden case, run the **real** loop, score it, judge it.

    from runbook.evals import CASES, run_evals
    report = await run_evals(CASES)
    print(report.format())

Calls `runbook.core.loop.diagnose` — the same function the CLI and dashboard
call. Never calls `core.store`: a run here produces no `incident_runs` row.

A crash in `diagnose()` for one case is caught and recorded as an errored
outcome (and fails the report) rather than aborting the whole run.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence

from ..core.loop import diagnose
from .cases import CASES, EvalCase
from .judge import judge
from .report import CaseOutcome, EvalReport
from .scorers import score_case

__all__ = ["CASES", "CaseOutcome", "run_evals"]

ProgressFn = Callable[[str], None]


async def _run_one(case: EvalCase, *, use_judge: bool, progress: ProgressFn | None) -> CaseOutcome:
    started = time.monotonic()
    usage = {"input_tokens": 0, "output_tokens": 0}
    try:
        result = await diagnose(case.alert, case.scenario)
    except Exception as exc:  # noqa: BLE001 - one bad case must not kill the run
        elapsed = time.monotonic() - started
        if progress:
            progress(f"  ✗ {case.id}: ERRORED — {exc}")
        return CaseOutcome(case, None, repr(exc), None, None, round(elapsed, 1), usage)

    usage["input_tokens"] += result.usage.get("input_tokens", 0)
    usage["output_tokens"] += result.usage.get("output_tokens", 0)

    scores = score_case(case, result)

    verdict = None
    if use_judge and case.judge and result.diagnosis is not None:
        try:
            verdict, jusage = await judge(case, result)
            usage["input_tokens"] += jusage.input_tokens
            usage["output_tokens"] += jusage.output_tokens
        except Exception as exc:  # noqa: BLE001 - a judge failure downgrades to "unjudged", not a crash
            if progress:
                progress(f"  ! {case.id}: judge failed — {exc}")

    elapsed = time.monotonic() - started
    if progress:
        mark = "✓" if scores.hard_ok else "✗"
        extra = f" judge={verdict.score}" if verdict else ""
        progress(f"  {mark} {case.id}  ({elapsed:.0f}s){extra}")
    return CaseOutcome(case, result, None, scores, verdict, round(elapsed, 1), usage)


async def run_evals(
    cases: Sequence[EvalCase] = CASES,
    *,
    use_judge: bool = True,
    concurrency: int = 4,
    progress: ProgressFn | None = None,
) -> EvalReport:
    """Run every case (bounded concurrency) and return the aggregated report."""
    sem = asyncio.Semaphore(concurrency)

    async def _guarded(c: EvalCase) -> CaseOutcome:
        async with sem:
            return await _run_one(c, use_judge=use_judge, progress=progress)

    outcomes = await asyncio.gather(*(_guarded(c) for c in cases))
    # keep report order stable = input order
    by_id = {o.case.id: o for o in outcomes}
    ordered = [by_id[c.id] for c in cases]
    return EvalReport.from_outcomes(ordered)
