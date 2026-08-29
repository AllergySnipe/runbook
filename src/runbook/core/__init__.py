"""Orchestration — the thin custom layer that runs the incident loop (ADR-0001).

The CLI, and later the dashboard + eval suite, all call the same function here.
"""

from __future__ import annotations

from .loop import DiagnoseResult, Diagnosis, RemediationStep, ToolCall, diagnose
from .triage import TriageResult, triage

__all__ = [
    "DiagnoseResult",
    "Diagnosis",
    "RemediationStep",
    "ToolCall",
    "TriageResult",
    "diagnose",
    "triage",
]
