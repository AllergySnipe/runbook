"""Persistence for incident runs — the audit record (SPEC S6) and the approval
gate (S1).

`diagnose()` produces a `DiagnoseResult` and returns; it does **not** touch the
database (so the eval suite can run the loop thousands of times without writing
to prod). The CLI — and later the dashboard — call `record_run()` to persist one
run, then `resolve_approvals()` when a human approves or rejects.

The gate is a **state machine, not a blocking call** (ADR-0007). A
`needs-approval` run is written as `awaiting-approval` with one `pending_approvals`
row per state-changing step; a separate, human-initiated command transitions
those rows and recomputes the run's `status`. Nothing waits on a thread.

S1 is structural: the only code that writes an approval state other than
`pending` is `resolve_approvals()`, and the only callers of that are the
`runbook approve|reject` commands. The loop has no path to it.

`compute_status()` is a pure function — that is where the lifecycle guarantee is
pinned and unit-tested; everything else here is a thin SQL shell around it.
"""

from __future__ import annotations

import dataclasses
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from ..db import connect

if TYPE_CHECKING:
    from .loop import DiagnoseResult

Status = Literal["short-circuited", "awaiting-approval", "resolved", "rejected", "escalated"]

TERMINAL: frozenset[str] = frozenset({"short-circuited", "resolved", "rejected", "escalated"})


# --- pure lifecycle logic (no DB) ----------------------------------------------


def compute_status(disposition: str | None, approval_states: list[str]) -> Status:
    """The run's lifecycle state, from the guardrail disposition plus the state of
    each pending-approval row. Pure — this is the S1 guarantee, unit-tested.

    - no disposition  → triage short-circuited the run
    - `auto`          → nothing to approve, resolved
    - `escalate`      → handed to a human, no gate
    - `needs-approval`→ `awaiting-approval` until every step is approved
                        (`resolved`), unless any is rejected (`rejected`)
    """
    if disposition is None:
        return "short-circuited"
    if disposition == "auto":
        return "resolved"
    if disposition == "escalate":
        return "escalated"
    # needs-approval
    if any(s == "rejected" for s in approval_states):
        return "rejected"
    if approval_states and all(s == "approved" for s in approval_states):
        return "resolved"
    return "awaiting-approval"


# --- records -----------------------------------------------------------------


@dataclass
class ApprovalRecord:
    id: int
    step_index: int
    action: str
    runbook_quote: str
    classifier_reason: str
    state: str
    resolved_by: str | None
    resolved_at: datetime | None
    note: str | None


@dataclass
class RunRecord:
    id: str
    alert: str
    scenario: str
    triage_category: str
    triage_rationale: str
    triage_confidence: str
    disposition: str | None
    status: str
    diagnosis: dict | None
    retrieved: list
    tool_calls: list
    guardrail: dict | None
    usage: dict
    iterations: int
    hit_max_iters: bool
    elapsed_s: float
    created_at: datetime
    resolved_at: datetime | None
    featured: bool = False
    approvals: list[ApprovalRecord] = field(default_factory=list)


# --- serialisation ---------------------------------------------------------


def _jsonify(obj: object) -> object:
    """Recursively convert dataclasses / Pydantic models / datetimes into
    JSON-safe primitives. `dataclasses.asdict` can't do this — it leaves nested
    Pydantic models (the second-pass concerns inside `GuardrailReport`) intact."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, datetime):
        return obj.isoformat()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _jsonify(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonify(v) for v in obj]
    return str(obj)


def _retrieved_json(chunks: list) -> list[dict]:
    return [
        {
            "title": c.title,
            "path": c.path,
            "source": c.source,
            "origin": c.origin,
            "heading": c.heading_display,
            "scores": c.scores,
        }
        for c in chunks
    ]


def _tool_calls_json(calls: list) -> list[dict]:
    out = []
    for t in calls:
        try:
            result = json.loads(t.result_json)
        except (ValueError, TypeError):
            result = t.result_json
        out.append({"name": t.name, "input": t.input, "is_error": t.is_error, "result": result})
    return out


_RUN_COLS = (
    "id, alert, scenario, triage_category, triage_rationale, triage_confidence, "
    "disposition, status, diagnosis, retrieved, tool_calls, guardrail, usage, "
    "iterations, hit_max_iters, elapsed_s, created_at, resolved_at, featured"
)


def _row_to_record(row: tuple, approvals: list[tuple]) -> RunRecord:
    return RunRecord(
        id=row[0],
        alert=row[1],
        scenario=row[2],
        triage_category=row[3],
        triage_rationale=row[4],
        triage_confidence=row[5],
        disposition=row[6],
        status=row[7],
        diagnosis=row[8],
        retrieved=row[9] or [],
        tool_calls=row[10] or [],
        guardrail=row[11],
        usage=row[12] or {},
        iterations=row[13],
        hit_max_iters=row[14],
        elapsed_s=float(row[15]),
        created_at=row[16],
        resolved_at=row[17],
        featured=bool(row[18]),
        approvals=[
            ApprovalRecord(
                id=a[0],
                step_index=a[1],
                action=a[2],
                runbook_quote=a[3],
                classifier_reason=a[4],
                state=a[5],
                resolved_by=a[6],
                resolved_at=a[7],
                note=a[8],
            )
            for a in approvals
        ],
    )


# --- writes / reads --------------------------------------------------------


def record_run(result: DiagnoseResult, *, run_id: str | None = None) -> RunRecord:
    """Persist one `diagnose()` run. For a `needs-approval` disposition, also
    write a `pending_approvals` row per state-changing step.

    `run_id` lets a caller pre-allocate the id (the dashboard returns it to the
    client before the loop finishes); the CLI omits it and one is generated."""
    run_id = run_id or "run_" + secrets.token_hex(4)
    d = result.diagnosis
    g = result.guardrail

    gated = (
        [v for v in g.verdicts if v.classification == "state-changing"]
        if g is not None and result.disposition == "needs-approval"
        else []
    )
    status = compute_status(result.disposition, ["pending"] * len(gated))

    with connect() as conn, conn.transaction():
        conn.execute(
            f"""
            insert into incident_runs (
                id, alert, scenario, triage_category, triage_rationale, triage_confidence,
                disposition, status, diagnosis, retrieved, tool_calls, guardrail,
                usage, iterations, hit_max_iters, elapsed_s, resolved_at
            ) values (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                %s::jsonb, %s, %s, %s, {"now()" if status in TERMINAL else "null"}
            )
            """,
            (
                run_id,
                result.alert,
                result.scenario,
                result.triage.category,
                result.triage.rationale,
                result.triage.confidence,
                result.disposition,
                status,
                json.dumps(_jsonify(d)) if d is not None else None,
                json.dumps(_retrieved_json(result.retrieved)),
                json.dumps(_tool_calls_json(result.tool_calls)),
                json.dumps(_jsonify(g)) if g is not None else None,
                json.dumps(result.usage),
                result.iterations,
                result.hit_max_iters,
                result.elapsed_s,
            ),
        )
        for v in gated:
            assert d is not None  # needs-approval ⇒ there are steps
            step = d.remediation_steps[v.step_index]
            conn.execute(
                """
                insert into pending_approvals
                    (run_id, step_index, action, runbook_quote, classifier_reason)
                values (%s, %s, %s, %s, %s)
                """,
                (run_id, v.step_index, step.action, step.runbook_quote, v.reason),
            )

    got = get_run(run_id)
    assert got is not None
    return got


def get_run(run_id: str) -> RunRecord | None:
    with connect() as conn:
        row = conn.execute(
            f"select {_RUN_COLS} from incident_runs where id = %s", (run_id,)
        ).fetchone()
        if row is None:
            return None
        approvals = conn.execute(
            "select id, step_index, action, runbook_quote, classifier_reason, state, "
            "resolved_by, resolved_at, note from pending_approvals "
            "where run_id = %s order by step_index",
            (run_id,),
        ).fetchall()
    return _row_to_record(row, approvals)


def list_runs(
    *, status: str | None = None, featured: bool | None = None, limit: int = 20
) -> list[RunRecord]:
    q = f"select {_RUN_COLS} from incident_runs"
    where, params = [], []
    if status:
        where.append("status = %s")
        params.append(status)
    if featured is not None:
        where.append("featured = %s")
        params.append(featured)
    if where:
        q += " where " + " and ".join(where)
    q += " order by created_at desc limit %s"
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(q, params).fetchall()
    return [_row_to_record(r, []) for r in rows]


def set_featured(run_id: str, on: bool) -> bool:
    """Mark/unmark a run as a curated exemplar. Returns True if the run exists."""
    with connect() as conn, conn.transaction():
        n = conn.execute(
            "update incident_runs set featured = %s where id = %s", (on, run_id)
        ).rowcount
    return n > 0


def resolve_approvals(
    run_id: str,
    *,
    decision: Literal["approve", "reject"],
    step: int | None = None,
    by: str,
    note: str | None = None,
) -> RunRecord:
    """Transition pending approvals and recompute the run's status, in one
    transaction. `step` is a 0-based index; `None` targets every pending step.
    A no-op (terminal run, or nothing pending) leaves the run untouched."""
    if decision not in ("approve", "reject"):
        raise ValueError(f"decision must be approve|reject, got {decision!r}")
    new_state = "approved" if decision == "approve" else "rejected"

    with connect() as conn, conn.transaction():
        run = conn.execute(
            "select status, disposition from incident_runs where id = %s for update",
            (run_id,),
        ).fetchone()
        if run is None:
            raise LookupError(f"no run {run_id!r}")
        status, disposition = run
        if status not in TERMINAL:
            if step is None:
                conn.execute(
                    "update pending_approvals set state = %s, resolved_by = %s, "
                    "resolved_at = now(), note = %s "
                    "where run_id = %s and state = 'pending'",
                    (new_state, by, note, run_id),
                )
            else:
                conn.execute(
                    "update pending_approvals set state = %s, resolved_by = %s, "
                    "resolved_at = now(), note = %s "
                    "where run_id = %s and step_index = %s and state = 'pending'",
                    (new_state, by, note, run_id, step),
                )
            states = [
                r[0]
                for r in conn.execute(
                    "select state from pending_approvals where run_id = %s", (run_id,)
                ).fetchall()
            ]
            new_status = compute_status(disposition, states)
            conn.execute(
                "update incident_runs set status = %s, "
                "resolved_at = case when %s and resolved_at is null then now() else resolved_at end "
                "where id = %s",
                (new_status, new_status in TERMINAL, run_id),
            )

    got = get_run(run_id)
    assert got is not None
    return got
