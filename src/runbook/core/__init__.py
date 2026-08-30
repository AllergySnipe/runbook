"""Orchestration — the thin custom layer that runs the incident loop (ADR-0001).

The CLI, and later the dashboard + eval suite, all call the same function here.
"""

from __future__ import annotations

from .guardrail import ActionVerdict, GuardrailReport, classify_action, classify_steps
from .loop import DiagnoseResult, Diagnosis, RemediationStep, ToolCall, diagnose
from .store import (
    ApprovalRecord,
    RunRecord,
    compute_status,
    get_run,
    list_runs,
    record_run,
    resolve_approvals,
    set_featured,
)
from .triage import TriageResult, triage

__all__ = [
    "ActionVerdict",
    "ApprovalRecord",
    "DiagnoseResult",
    "Diagnosis",
    "GuardrailReport",
    "RemediationStep",
    "RunRecord",
    "ToolCall",
    "TriageResult",
    "classify_action",
    "classify_steps",
    "compute_status",
    "diagnose",
    "get_run",
    "list_runs",
    "record_run",
    "resolve_approvals",
    "set_featured",
    "triage",
]
