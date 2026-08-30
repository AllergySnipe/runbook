"""Progress events emitted by `diagnose()` as it runs.

The loop (`core/loop.py`) is otherwise a black box: it runs for ~30-60s and
returns a `DiagnoseResult`. The CLI is happy to wait for that; the dashboard is
not — it wants to animate a timeline while the loop works. So `diagnose()` takes
an optional `on_event` callback and calls it at each milestone.

This is **narration, not state**. If nobody is listening the events vanish; the
truth is still the returned `DiagnoseResult` and the Postgres row written from it
(SPEC S6). SSE never becomes load-bearing.

`SCHEMA_VERSION` is bumped whenever the shape or the set of `type`s changes — the
frontend's timeline reducer is pinned to it (ADR-0010).
"""

from __future__ import annotations

from typing import Any, TypedDict

SCHEMA_VERSION = 4  # +memory.hit (incident memory, ADR-0015)


class Event(TypedDict):
    type: str
    data: dict[str, Any]


# --- event types -------------------------------------------------------------
# Kept flat and coarse: one per user-visible milestone, not one per function call.

CACHE_HIT = "cache.hit"  # semantic cache: a near-duplicate alert — triage + retrieval reused
MEMORY_HIT = "memory.hit"  # incident memory: similar past incident(s) shown to the diagnosis model
TRIAGE_START = "triage.start"
TRIAGE_DONE = "triage.done"
SHORT_CIRCUIT = "short_circuit"  # triage routed this out of the loop
RETRIEVE_START = "retrieve.start"
RETRIEVE_DONE = "retrieve.done"
TOOL_CALL = "tool_call"  # one read-only tool executed
REDACTION = "redaction"  # S5: secrets/PII scrubbed from tool output before it entered history
SYNTHESIS_START = "synthesis.start"
SYNTHESIS_DONE = "synthesis.done"
GROUNDING_REGENERATED = "grounding.regenerated"  # S3: a step failed the quote check
GROUNDING_DROPPED = "grounding.dropped"  # S3: still ungrounded after regen → dropped
GUARDRAIL_START = "guardrail.start"
GUARDRAIL_DONE = "guardrail.done"
DISPOSITION = "disposition"  # final: auto | needs-approval | escalate
ERROR = "error"  # the loop raised; the run is over
FINISHED = "finished"  # emitted by the API after the Postgres write — carries run_id + status


def event(type: str, /, **data: Any) -> Event:
    return {"type": type, "data": data}
