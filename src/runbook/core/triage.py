"""Triage: the cheap first look that routes an alert into a handling lane.

An alert arrives (Alertmanager JSON or free text). Before we spend a Sonnet
tool-loop on it, a prompted classifier on the cheap model (`settings.triage_model`)
picks one of four categories:

- `known-runbook`     — looks like a failure mode we have a runbook for → run the loop
- `novel-incident`    — a real incident, nothing written down → run the loop, low prior
- `noise-or-flapping` — not a real incident → short-circuit
- `need-more-info`     — not enough to act on → short-circuit, ask for specifics

Design (see LEARNINGS Week 2 — triage):

- **Prompted, not trained.** No labelled data yet; iterate by editing
  `prompts/triage.md`. Every confirmed/corrected decision becomes a future
  training example (the flywheel). Fine-tuning is the Week 4 stretch.
- **Recall on "real incident" beats precision** (SPEC eval criteria). Suppressing
  a real page is catastrophic; running the loop on noise costs ~$0.10. The prompt
  is worded to be reluctant to call something noise.
- **The alert text is untrusted** (S4). It can be attacker-influenced (a crafted
  log string echoed into an annotation). It goes into the prompt as data.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .. import llm
from ..config import get_settings
from ..prompts import load as load_prompt

Category = Literal["known-runbook", "novel-incident", "noise-or-flapping", "need-more-info"]

_PROCEED: set[Category] = {"known-runbook", "novel-incident"}


class TriageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category
    rationale: str = Field(description="one sentence — why this lane")
    confidence: Literal["low", "medium", "high"]

    @property
    def proceed(self) -> bool:
        """Whether the full diagnosis loop should run."""
        return self.category in _PROCEED

    @property
    def low_prior(self) -> bool:
        """Novel incident: retrieval will surface a runbook, but it's probably only
        loosely relevant — downstream should lean on tool evidence and escalation."""
        return self.category == "novel-incident"


def _normalise_alert(alert: str | dict) -> str:
    """Collapse either an Alertmanager webhook payload or free text into one
    compact, labelled block the classifier always sees in the same shape.

    Alertmanager posts a JSON envelope with `alerts: [...]`; we pull the fields
    that matter for routing (name, service, severity, symptom text, and the
    firing/resolved + timestamps that reveal a flap). Anything else — a plain
    string, JSON we don't recognise — is passed through as the symptom text.
    """
    payload: dict | None = None
    if isinstance(alert, dict):
        payload = alert
    elif isinstance(alert, str):
        stripped = alert.strip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    payload = parsed
            except json.JSONDecodeError:
                payload = None

    if payload is None or "alerts" not in payload:
        text = alert if isinstance(alert, str) else json.dumps(alert)
        return f"Free-text incident report:\n{text.strip()}"

    common_labels = payload.get("commonLabels", {}) or {}
    common_annotations = payload.get("commonAnnotations", {}) or {}
    alerts = payload.get("alerts") or []

    lines = [f"Alertmanager payload — status={payload.get('status', '?')}, {len(alerts)} alert(s)"]

    def _emit(prefix: str, labels: dict, annotations: dict, extra: dict | None = None) -> None:
        name = labels.get("alertname") or "(no alertname)"
        parts = [f"{prefix}{name}"]
        for key in ("service", "severity", "namespace", "instance"):
            if labels.get(key):
                parts.append(f"{key}={labels[key]}")
        lines.append("  ".join(parts))
        for key in ("summary", "description", "runbook_url"):
            if annotations.get(key):
                lines.append(f"    {key}: {annotations[key]}")
        for key in ("status", "startsAt", "endsAt"):
            if extra and extra.get(key):
                lines.append(f"    {key}: {extra[key]}")

    _emit("common: ", common_labels, common_annotations)
    for a in alerts:
        _emit(
            "  - ",
            a.get("labels", {}) or {},
            a.get("annotations", {}) or {},
            {"status": a.get("status"), "startsAt": a.get("startsAt"), "endsAt": a.get("endsAt")},
        )
    return "\n".join(lines)


async def triage(alert: str | dict, *, model: str | None = None) -> TriageResult:
    """Classify one alert into a handling lane. One cheap model call."""
    settings = get_settings()
    model = model or settings.triage_model
    system = load_prompt("triage")
    normalised = _normalise_alert(alert)
    messages = [{"role": "user", "content": f"Classify this alert:\n\n{normalised}"}]
    result, _usage = await llm.parse(
        messages,
        model=model,
        system=system,
        schema=TriageResult,
        fallbacks=settings.structured_fallbacks,
    )
    return result
