"""Promote a real incident run into a golden eval case — the prod→eval half of the
flywheel (project-plan Week 3: "failing eval/prod traces → new golden cases"; ADR-0016).

This does NOT auto-append to `cases.py`. `cases.py` is emphatic that labels are
hand-set ground truth — a wrong label punishes a correct answer. So `promote`
renders a ready-to-paste `EvalCase(...)` stub with the mechanical fields filled
(alert, scenario) and every *label* marked for the human to confirm, seeded with
what the run produced and — where available — the human-confirmed outcome
(`runbook outcome`). The human pastes it into the right list in `cases.py`,
checks each label against the scenario fixture, and commits.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime

_TRIAGE_CONST = {
    "known-runbook": "TRIAGE_KNOWN",
    "novel-incident": "TRIAGE_NOVEL",
    "noise-or-flapping": "TRIAGE_NOISE",
    "need-more-info": "TRIAGE_NEEDINFO",
}


def _opt_str(v: str | None) -> str:
    return f'"{v}"' if v else "None"


def _pystr(s: str, indent: int) -> str:
    """A string literal for the stub: `repr` if short, else parenthesised
    implicit-concatenation wrapped to ~88 cols (matching the file's style)."""
    if len(s) + indent <= 84 and "\n" not in s:
        return repr(s)
    pad = " " * indent
    lines = textwrap.wrap(s, width=84 - indent, break_long_words=False, break_on_hyphens=False)
    # implicit string concat drops the newline — carry the join space on each line
    lines = [ln + " " for ln in lines[:-1]] + lines[-1:]
    body = "\n".join(f"{pad}    {ln!r}" for ln in lines)
    return f"(\n{body}\n{pad})"


def _runbook_guess(run) -> str | None:
    for c in run.retrieved:
        path = c.get("path") or ""
        if "corpus/synthetic/" in path and path.endswith(".md"):
            return path.rsplit("/", 1)[-1]
    return None


def render_case_stub(run, outcome=None) -> str:
    """The `EvalCase(...)` source for one promoted run. `run` is a
    `store.RunRecord`; `outcome` an optional `memory.OutcomeRecord`."""
    short = run.id.removeprefix("run_")[:8]
    diag = run.diagnosis or {}
    triage_const = _TRIAGE_CONST.get(run.triage_category, f'"{run.triage_category}"')
    failure_mode = (
        (outcome.actual_failure_mode if outcome else None) or diag.get("failure_mode") or "unknown"
    )
    ref_rc = outcome.actual_root_cause if outcome else diag.get("root_cause", "")
    rc_source = (
        f"human-confirmed by {outcome.created_by}"
        if outcome
        else "!!! MODEL'S UNVERIFIED GUESS — replace with the confirmed root cause"
    )
    rb = _runbook_guess(run)
    note = (
        f"promoted from {run.id}"
        + (f" (outcome recorded by {outcome.created_by})" if outcome else " (NO recorded outcome)")
        + f" on {datetime.now(UTC):%Y-%m-%d}"
    )

    return "\n".join(
        [
            "    # --- TODO: confirm every label below against the scenario fixture + runbook,",
            "    #          then move this into the right list above and delete this comment.",
            "    EvalCase(",
            f'        id="promoted/{run.scenario}-{short}",',
            f"        alert={_pystr(run.alert, 8)},",
            f'        scenario="{run.scenario}",',
            f"        expect_triage={triage_const},  # run said: {run.triage_category}",
            f"        expect_runbook={_opt_str(rb)},  # TODO confirm",
            f'        expect_failure_mode="{failure_mode}",  # TODO confirm',
            f'        expect_disposition="{run.disposition}",  # run said: {run.disposition} — TODO confirm',
            f"        reference_root_cause={_pystr(ref_rc, 8)},  # {rc_source}",
            f"        notes={_pystr(note, 8)},",
            "    ),",
        ]
    )
