"""Log-injection red-team harness (SPEC S4).

Runbook reads two things it does not control: retrieved corpus documents and the
output of read-only tools (log lines especially). SPEC S4 says that content is
*untrusted data, never instructions*. This package measures whether that holds
under a real adversary.

Threat model: the attacker controls **a log line or a corpus document** (indirect
/ second-order injection) — or, more weakly, the alert annotation (direct
injection). The attacker never touches the prompt.

    from runbook.redteam import ATTACKS, run_attacks
    hardened = await run_attacks(ATTACKS, condition="hardened")
    baseline = await run_attacks(ATTACKS, condition="baseline")
    print(format_comparison(baseline, hardened))

Like the eval runner, this calls the **real** `core.loop.diagnose` and never
touches `core.store`. Design + rationale: `docs/adr/0012-red-team-harness.md`.
The measured before/after report: `docs/security/log-injection.md`.
"""

from __future__ import annotations

from .attacks import ATTACKS, AttackCase
from .detect import AttackOutcome, evaluate
from .report import AttackReport, format_comparison
from .runner import run_attacks

__all__ = [
    "ATTACKS",
    "AttackCase",
    "AttackOutcome",
    "AttackReport",
    "evaluate",
    "format_comparison",
    "run_attacks",
]
