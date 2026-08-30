"""The eval suite — how we know the probabilistic parts of the loop are good
enough to point at on-call (SPEC "How we'll know it works").

Deterministic code gets `pytest`; the model-driven behaviour — triage routing,
hybrid retrieval, the tool loop, synthesis, the guardrail second pass — gets an
*eval*: a hand-labelled set of realistic alerts (`cases.py`), scored against what
a competent responder would conclude (`scorers.py` + `judge.py`), run through the
**real** `diagnose()` code path (`runner.py`), summarised as a scorecard with a
committed regression baseline (`report.py`).

Two rules the design turns on (see ADR-0008):

- **Same code path as prod.** The runner calls `runbook.core.loop.diagnose` — the
  exact function the CLI and dashboard call. No re-implementation to drift from.
- **Never persists.** `diagnose()` touches no database; the runner never imports
  `core.store`. A 30-case run must not write 30 rows into the S6 audit log.

Entry point: `runbook eval` (see `cli.py`). Needs `ANTHROPIC_API_KEY` +
`DATABASE_URL` — it makes real model calls and real retrieval queries.
"""

from __future__ import annotations

from .cases import CASES, EvalCase
from .promote import render_case_stub
from .report import CaseOutcome, EvalReport, bless_from_json, load_baseline, write_baseline
from .runner import run_evals

__all__ = [
    "CASES",
    "CaseOutcome",
    "EvalCase",
    "EvalReport",
    "bless_from_json",
    "load_baseline",
    "render_case_stub",
    "run_evals",
    "write_baseline",
]
