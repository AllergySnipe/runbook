"""The runner: for each attack case, splice the payload into its surface, run the
**real** loop, and check whether the attack worked.

    from runbook.redteam import ATTACKS, run_attacks
    hardened = await run_attacks(ATTACKS, condition="hardened")
    baseline = await run_attacks(ATTACKS, condition="baseline")

Calls `runbook.core.loop.diagnose` — the same function the CLI and dashboard
call. Never calls `core.store`. A crash in one case is caught and recorded, not
allowed to abort the run (mirrors `evals/runner.py`).

The `control/*` cases run first: their dispositions are the per-scenario baseline
that disposition manipulation is judged against (`detect.evaluate`).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from typing import Literal

from ..core.loop import diagnose
from ..sim import load_scenario
from .ablate import prompt_defences_disabled
from .attacks import ATTACKS, AttackCase
from .detect import AttackOutcome, errored_outcome, outcome
from .inject import alert_for, injected
from .report import AttackReport

__all__ = ["ATTACKS", "AttackOutcome", "AttackReport", "run_attacks"]

Condition = Literal["hardened", "baseline"]
ProgressFn = Callable[[str], None]


async def _diagnose_case(case: AttackCase, condition: Condition):
    load_scenario(case.scenario)  # fail fast on a bad scenario name
    alert = alert_for(case, case.base_alert)
    with injected(case):
        if condition == "baseline":
            with prompt_defences_disabled():
                return await diagnose(alert, case.scenario)
        return await diagnose(alert, case.scenario)


async def _run_one(
    case: AttackCase,
    *,
    condition: Condition,
    controls: dict[str, str | None],
    progress: ProgressFn | None,
) -> AttackOutcome:
    started = time.monotonic()
    try:
        result = await _diagnose_case(case, condition)
    except Exception as exc:  # noqa: BLE001 - one bad case must not kill the run
        oc = errored_outcome(case, exc, elapsed_s=time.monotonic() - started)
        if progress:
            progress(f"  ✗ {case.id}: ERRORED — {exc}")
        return oc

    usage = {
        "input_tokens": result.usage.get("input_tokens", 0),
        "output_tokens": result.usage.get("output_tokens", 0),
    }
    oc = outcome(
        case,
        result,
        elapsed_s=time.monotonic() - started,
        usage=usage,
        control_disposition=controls.get(case.scenario),
    )
    if progress:
        mark = (
            "✗ ATTACK SUCCEEDED"
            if oc.succeeded
            else ("· control" if case.goal == "control" else "✓ held")
        )
        extra = f"  [{', '.join(oc.signals)}]" if oc.signals else ""
        progress(f"  {mark:18s} {case.id} ({oc.elapsed_s:.0f}s) → {oc.disposition}{extra}")
    return oc


async def run_attacks(
    cases: Sequence[AttackCase] = ATTACKS,
    *,
    condition: Condition = "hardened",
    concurrency: int = 2,
    progress: ProgressFn | None = None,
) -> AttackReport:
    """Run every case (bounded concurrency) under one condition. `control/*` cases
    run first so their dispositions can seed the per-scenario baseline."""
    sem = asyncio.Semaphore(concurrency)

    async def _guarded(c: AttackCase, controls: dict[str, str | None]) -> AttackOutcome:
        async with sem:
            return await _run_one(c, condition=condition, controls=controls, progress=progress)

    control_cases = [c for c in cases if c.id.startswith("control/")]
    attack_cases = [c for c in cases if not c.id.startswith("control/")]

    control_outcomes = await asyncio.gather(*(_guarded(c, {}) for c in control_cases))
    controls: dict[str, str | None] = {
        o.case.scenario: o.disposition for o in control_outcomes if o.error is None
    }

    attack_outcomes = await asyncio.gather(*(_guarded(c, controls) for c in attack_cases))

    by_id = {o.case.id: o for o in (*control_outcomes, *attack_outcomes)}
    ordered = [by_id[c.id] for c in cases]
    return AttackReport.from_outcomes(ordered, condition=condition)
