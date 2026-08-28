"""The sim — a fixture-backed fake environment standing in for real infrastructure.

`SPEC.md` non-goals: *"No real infrastructure integration. The sim is the world."*
So this package holds hand-authored scenarios (one per modelled failure mode, plus
a `healthy` baseline). Each scenario fixes `paymentsvc`'s world for an incident
window: metric time-series, a log stream, a deploy history, a service-dependency
graph. The read-only tool layer (`runbook.tools`) queries a loaded scenario; the
agent loop (next slice) drives the tools.

Why fixtures, not a real backend: determinism (evals + CI need identical inputs
every run), no credentials / offline (same rationale as ADR-0002), and we author
the signal on purpose — each scenario is built so that running its runbook's
Diagnosis steps against it reaches that runbook's conclusion. See ADR-0004.

Public surface:

    from runbook.sim import load_scenario, list_scenarios
"""

from __future__ import annotations

from .scenario import Scenario, list_scenarios, load_scenario

__all__ = ["Scenario", "list_scenarios", "load_scenario"]
