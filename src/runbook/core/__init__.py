"""Orchestration — the thin custom layer that runs the incident loop (ADR-0001).

The CLI, and later the dashboard + eval suite, all call the same function here.
"""

from __future__ import annotations

from .guardrail import ActionVerdict, GuardrailReport, classify_action, classify_steps
from .loop import DiagnoseResult, Diagnosis, RemediationStep, ToolCall, diagnose
from .memory import MemoryHit, OutcomeRecord, OutcomeResult, get_outcome, record_outcome
from .scoring import score_and_record, score_run, should_score
from .store import (
    ApprovalRecord,
    RunRecord,
    ScoreRecord,
    compute_status,
    get_run,
    get_scores,
    list_recent_scores,
    list_runs,
    mark_run_failed,
    record_online_scores,
    record_run,
    record_run_start,
    resolve_approvals,
    run_stats,
    set_featured,
)
from .triage import TriageResult, triage

__all__ = [
    "ActionVerdict",
    "ApprovalRecord",
    "DiagnoseResult",
    "Diagnosis",
    "GuardrailReport",
    "MemoryHit",
    "OutcomeRecord",
    "OutcomeResult",
    "RemediationStep",
    "RunRecord",
    "ScoreRecord",
    "ToolCall",
    "TriageResult",
    "classify_action",
    "classify_steps",
    "compute_status",
    "diagnose",
    "get_outcome",
    "get_run",
    "get_scores",
    "list_recent_scores",
    "list_runs",
    "mark_run_failed",
    "record_online_scores",
    "record_outcome",
    "record_run",
    "record_run_start",
    "resolve_approvals",
    "run_stats",
    "score_and_record",
    "score_run",
    "set_featured",
    "should_score",
    "triage",
]
