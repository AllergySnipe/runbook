"""Aggregation, the scorecard, and the regression baseline.

`EvalReport.from_outcomes` rolls per-case scores into metrics; `format()` prints
the scorecard; `regressions()` compares against `baseline.json` (committed).

The baseline is the SPEC regression rule made concrete: *"no eval metric drops
between commits without a written justification."* A metric that falls more than
`TOLERANCE` below its blessed value **and** below its target fails the run.
Re-blessing (`runbook eval --update-baseline` on a fresh run, or `--bless
<results.json>` from one you already ran) is the written justification — it shows
up as a diff to a committed file in the PR.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .cases import EvalCase
from .judge import JudgeVerdict
from .scorers import CaseScores, HardFinding, actual_disposition

BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"
TOLERANCE = 0.05  # run-to-run noise we tolerate before calling a drop a regression


@dataclass
class MetricSpec:
    name: str
    target: float
    blurb: str


METRICS: list[MetricSpec] = [
    MetricSpec("triage_accuracy", 0.90, "triage category == label"),
    MetricSpec(
        "triage_incident_recall", 0.95, "real incidents triage let through (not suppressed)"
    ),
    MetricSpec("retrieval_hit_at_3", 0.85, "expected runbook in retrieved top-3"),
    MetricSpec("failure_mode_exact", 0.80, "diagnosis.failure_mode == label"),
    MetricSpec(
        "disposition_match", 0.85, "auto / needs-approval / escalate / short-circuit == label"
    ),
    MetricSpec("judge_mean_norm", 0.80, "LLM-judge root-cause score, mean / 5"),
    MetricSpec("judge_pass_rate", 0.85, "LLM-judge score >= 3 (responder not misled)"),
]


@dataclass
class CaseOutcome:
    case: EvalCase
    result: object | None  # DiagnoseResult, or None if diagnose() raised
    error: str | None
    scores: CaseScores | None
    judge: JudgeVerdict | None
    elapsed_s: float
    usage: dict[str, int]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


@dataclass
class EvalReport:
    outcomes: list[CaseOutcome]
    metrics: dict[str, float | None]
    hard_findings: list[HardFinding]
    n_cases: int
    n_errored: int
    n_judged: int
    tokens: dict[str, int]
    generated_at: str

    @classmethod
    def from_outcomes(cls, outcomes: list[CaseOutcome]) -> EvalReport:
        scored = [o for o in outcomes if o.scores is not None]

        def collect(attr: str) -> list[float]:
            out = []
            for o in scored:
                v = getattr(o.scores, attr)
                if v is not None:
                    out.append(float(v))
            return out

        judged = [o for o in outcomes if o.judge is not None]
        judge_scores = [o.judge.score for o in judged]

        metrics: dict[str, float | None] = {
            "triage_accuracy": _mean(collect("triage_correct")),
            "triage_incident_recall": _mean(collect("triage_incident_recalled")),
            "retrieval_hit_at_3": _mean(collect("retrieval_hit_at_3")),
            "failure_mode_exact": _mean(collect("failure_mode_correct")),
            "disposition_match": _mean(collect("disposition_correct")),
            "judge_mean_norm": (_mean([s / 5 for s in judge_scores])),
            "judge_pass_rate": _mean([float(s >= 3) for s in judge_scores])
            if judge_scores
            else None,
        }

        hard: list[HardFinding] = []
        for o in scored:
            hard.extend(o.scores.hard_findings)

        tokens = {"input_tokens": 0, "output_tokens": 0}
        for o in outcomes:
            tokens["input_tokens"] += o.usage.get("input_tokens", 0)
            tokens["output_tokens"] += o.usage.get("output_tokens", 0)

        return cls(
            outcomes=outcomes,
            metrics=metrics,
            hard_findings=hard,
            n_cases=len(outcomes),
            n_errored=sum(1 for o in outcomes if o.error),
            n_judged=len(judged),
            tokens=tokens,
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

    # --- verdict --------------------------------------------------------------

    def below_target(self) -> list[str]:
        out = []
        for m in METRICS:
            v = self.metrics.get(m.name)
            if v is not None and v < m.target:
                out.append(f"{m.name} {v:.2f} < target {m.target:.2f}")
        return out

    def regressions(self, baseline: dict | None) -> list[str]:
        """Metrics that dropped meaningfully below the blessed baseline *and* sit
        below target. A drop that stays above target is noise we allow."""
        if not baseline:
            return []
        base = baseline.get("metrics", {})
        targets = {m.name: m.target for m in METRICS}
        out = []
        for name, v in self.metrics.items():
            b = base.get(name)
            if v is None or b is None:
                continue
            if v < b - TOLERANCE and v < targets.get(name, 1.0):
                out.append(f"{name}: {v:.2f} vs baseline {b:.2f} (-{b - v:.2f})")
        return out

    def passed(self, baseline: dict | None) -> bool:
        return (
            not self.hard_findings
            and self.n_errored == 0
            and not self.below_target()
            and not self.regressions(baseline)
        )

    # --- formatting ----------------------------------------------------------

    def format(self, baseline: dict | None = None) -> str:
        base = (baseline or {}).get("metrics", {})
        lines: list[str] = []
        lines.append(f"eval scorecard — {self.n_cases} cases, {self.generated_at}")
        if self.n_errored:
            lines.append(f"  ⚠ {self.n_errored} case(s) errored in diagnose() — see below")
        lines.append("")
        lines.append(f"  {'metric':24s} {'value':>7s} {'target':>7s} {'base':>7s}   note")
        lines.append("  " + "-" * 72)
        for m in METRICS:
            v = self.metrics.get(m.name)
            b = base.get(m.name)
            vs = "  n/a  " if v is None else f"{v:6.2f} "
            bs = "   —   " if b is None else f"{b:6.2f} "
            mark = " " if v is None else ("✓" if v >= m.target else "✗")
            lines.append(f"  {m.name:24s} {vs} {m.target:6.2f}  {bs} {mark} {m.blurb}")
        lines.append("")

        if self.hard_findings:
            lines.append(f"  HARD CHECK FAILURES ({len(self.hard_findings)}) — must be zero:")
            for f_ in self.hard_findings:
                lines.append(f"    ✗ [{f_.check}] {f_.case_id}: {f_.detail}")
            lines.append("")
        else:
            lines.append("  hard checks: all clear (action-safety, tool-allowlist, groundedness)")
            lines.append("")

        misses = self._case_misses()
        if misses:
            lines.append("  per-case misses:")
            for line in misses:
                lines.append(f"    {line}")
            lines.append("")

        reg = self.regressions(baseline)
        if reg:
            lines.append("  REGRESSIONS vs baseline:")
            for r in reg:
                lines.append(f"    ✗ {r}")
            lines.append("")

        tok = self.tokens
        lines.append(
            f"  tokens: {tok['input_tokens']:,} in / {tok['output_tokens']:,} out"
            f"   ·   {self.n_judged} judged   ·   ~{self._request_estimate()} requests"
            f"  (free tier: 20/min, 1000/day — ADR-0009)"
        )
        verdict = "PASS" if self.passed(baseline) else "FAIL"
        lines.append(f"\n  → {verdict}")
        return "\n".join(lines)

    def _case_misses(self) -> list[str]:
        out = []
        for o in self.outcomes:
            if o.error:
                out.append(f"{o.case.id}: ERRORED — {o.error}")
                continue
            s = o.scores
            if s is None:
                continue
            bits = []
            if not s.triage_correct:
                bits.append(f"triage={o.result.triage.category} (want {o.case.expect_triage})")
            if s.retrieval_hit_at_3 is False:
                bits.append("retrieval miss")
            if s.failure_mode_correct is False:
                bits.append(
                    f"fm={o.result.diagnosis.failure_mode} (want {o.case.expect_failure_mode})"
                )
            if not s.disposition_correct:
                bits.append(
                    f"disp={actual_disposition(o.result)} (want {o.case.expect_disposition})"
                )
            if o.judge is not None and o.judge.score <= 2:
                bits.append(f"judge={o.judge.score} ({o.judge.rationale})")
            if bits:
                out.append(f"{o.case.id}: " + "; ".join(bits))
        return out

    def _request_estimate(self) -> int:
        """Rough request count (what the free-tier caps are denominated in).
        ~1 triage + ~4 tool turns + 1 synthesis + 1 second-pass per non-short-circuit
        case, + 1 judge for judged cases."""
        n = sum(1 for o in self.outcomes if o.error is None)
        return n * 7 + self.n_judged

    def as_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "n_cases": self.n_cases,
            "n_errored": self.n_errored,
            "metrics": self.metrics,
            "hard_findings": [
                {"check": f_.check, "case_id": f_.case_id, "detail": f_.detail}
                for f_ in self.hard_findings
            ],
            "tokens": self.tokens,
            "cases": [
                {
                    "id": o.case.id,
                    "error": o.error,
                    "triage": o.result.triage.category if o.result else None,
                    "disposition": actual_disposition(o.result) if o.result else None,
                    "failure_mode": (
                        o.result.diagnosis.failure_mode if o.result and o.result.diagnosis else None
                    ),
                    "judge_score": o.judge.score if o.judge else None,
                    "elapsed_s": o.elapsed_s,
                }
                for o in self.outcomes
            ],
        }


# --- baseline i/o ------------------------------------------------------------


def load_baseline() -> dict | None:
    if not BASELINE_PATH.is_file():
        return None
    return json.loads(BASELINE_PATH.read_text())


def _write_baseline_dict(blessed_at: str, n_cases: int, metrics: dict) -> None:
    BASELINE_PATH.write_text(
        json.dumps(
            {
                "blessed_at": blessed_at,
                "n_cases": n_cases,
                "metrics": {
                    k: (round(v, 4) if v is not None else None) for k, v in metrics.items()
                },
            },
            indent=2,
        )
        + "\n"
    )


def write_baseline(report: EvalReport) -> None:
    _write_baseline_dict(report.generated_at, report.n_cases, report.metrics)


def bless_from_json(path: str) -> dict:
    """Bless the baseline from a prior `runbook eval --json` result file, without
    re-running. Refuses a run with errored cases or hard failures. Returns the
    metrics written."""
    d = json.loads(Path(path).read_text())
    if d.get("n_errored"):
        raise ValueError(f"{path}: {d['n_errored']} errored case(s) — not a clean run")
    if d.get("hard_findings"):
        raise ValueError(f"{path}: {len(d['hard_findings'])} hard-check failure(s)")
    _write_baseline_dict(d["generated_at"], d["n_cases"], d["metrics"])
    return d["metrics"]
