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
from .cost import estimate_cost

if TYPE_CHECKING:
    from .loop import DiagnoseResult

Status = Literal[
    "running",  # web_api pre-persists a stub at kickoff so a crashed run still has a row
    "short-circuited",
    "awaiting-approval",
    "resolved",
    "rejected",
    "escalated",
    "failed",  # diagnose() raised — the stub was marked, not left dangling
]

TERMINAL: frozenset[str] = frozenset(
    {"short-circuited", "resolved", "rejected", "escalated", "failed"}
)


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
    redactions: int = 0
    cost_usd: float = 0.0  # est. $ at paid model prices (ADR-0014)
    cache_hit: bool = False  # semantic cache served the triage + retrieval prefix
    memories: list = field(default_factory=list)  # similar past incidents shown (ADR-0015)
    langfuse_trace_id: str | None = None  # the run's Langfuse trace, if tracing was on (ADR-0017)
    langfuse_trace_url: str | None = None
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


def _memories_json(memories: list) -> list[dict]:
    """The similar past incidents shown to the diagnosis model this run (ADR-0015)
    — part of the audit record's 'what was retrieved'."""
    return [
        {
            "entry_id": m.entry_id,
            "similarity": round(m.similarity, 4),
            "age_days": m.age_days,
            "scenario": m.scenario,
            "actual_root_cause": m.actual_root_cause,
            "actual_failure_mode": m.actual_failure_mode,
            "model_was_correct": m.model_was_correct,
        }
        for m in memories
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
    "iterations, hit_max_iters, elapsed_s, created_at, resolved_at, featured, redactions, "
    "cost_usd, cache_hit, memories, langfuse_trace_id, langfuse_trace_url"
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
        redactions=row[19] or 0,
        cost_usd=float(row[20] or 0),
        cache_hit=bool(row[21]),
        memories=row[22] or [],
        langfuse_trace_id=row[23],
        langfuse_trace_url=row[24],
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


def record_run_start(run_id: str, alert: str, scenario: str) -> None:
    """Write a `status='running'` stub the moment a dashboard run is kicked off,
    so a run that crashes mid-loop still has a row (and doesn't 404 the UI).
    `record_run` upserts the real data over it; `mark_run_failed` marks it on a
    crash. No-op on id conflict — a retry of the same id keeps the first stub."""
    with connect() as conn, conn.transaction():
        conn.execute(
            """
            insert into incident_runs (id, alert, scenario, triage_category,
                triage_rationale, triage_confidence, status)
            values (%s, %s, %s, '', '', '', 'running')
            on conflict (id) do nothing
            """,
            (run_id, alert, scenario),
        )


def mark_run_failed(run_id: str, error: str) -> None:
    """Move a `running` stub to `failed` with the error text (truncated). Only
    touches a non-terminal row, so it can't clobber a run that actually finished."""
    with connect() as conn, conn.transaction():
        conn.execute(
            "update incident_runs set status = 'failed', "
            "diagnosis = jsonb_build_object('error', %s::text), resolved_at = now() "
            "where id = %s and status not in "
            "('resolved', 'rejected', 'escalated', 'short-circuited')",
            (error[:500], run_id),
        )


def record_run(result: DiagnoseResult, *, run_id: str | None = None) -> RunRecord:
    """Persist one `diagnose()` run. For a `needs-approval` disposition, also
    write a `pending_approvals` row per state-changing step.

    `run_id` lets a caller pre-allocate the id (the dashboard returns it to the
    client before the loop finishes); the CLI omits it and one is generated.
    Upserts, so it overwrites a `record_run_start` stub for the same id."""
    run_id = run_id or "run_" + secrets.token_hex(4)
    d = result.diagnosis
    g = result.guardrail

    gated = (
        [v for v in g.verdicts if v.classification == "state-changing"]
        if g is not None and result.disposition == "needs-approval"
        else []
    )
    status = compute_status(result.disposition, ["pending"] * len(gated))
    cost_usd = estimate_cost(result.usage.get("by_model"))

    with connect() as conn, conn.transaction():
        conn.execute(
            f"""
            insert into incident_runs (
                id, alert, scenario, triage_category, triage_rationale, triage_confidence,
                disposition, status, diagnosis, retrieved, tool_calls, guardrail,
                usage, iterations, hit_max_iters, elapsed_s, redactions, cost_usd,
                cache_hit, memories, langfuse_trace_id, langfuse_trace_url, resolved_at
            ) values (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                %s::jsonb, %s, %s, %s, %s, %s,
                %s, %s::jsonb, %s, %s, {"now()" if status in TERMINAL else "null"}
            )
            on conflict (id) do update set
                alert = excluded.alert, scenario = excluded.scenario,
                triage_category = excluded.triage_category,
                triage_rationale = excluded.triage_rationale,
                triage_confidence = excluded.triage_confidence,
                disposition = excluded.disposition, status = excluded.status,
                diagnosis = excluded.diagnosis, retrieved = excluded.retrieved,
                tool_calls = excluded.tool_calls, guardrail = excluded.guardrail,
                usage = excluded.usage, iterations = excluded.iterations,
                hit_max_iters = excluded.hit_max_iters, elapsed_s = excluded.elapsed_s,
                redactions = excluded.redactions, cost_usd = excluded.cost_usd,
                cache_hit = excluded.cache_hit, memories = excluded.memories,
                langfuse_trace_id = excluded.langfuse_trace_id,
                langfuse_trace_url = excluded.langfuse_trace_url,
                resolved_at = excluded.resolved_at
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
                result.redaction_count,
                cost_usd,
                result.cache_hit,
                json.dumps(_memories_json(result.memories)),
                result.langfuse_trace_id,
                result.langfuse_trace_url,
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
                on conflict (run_id, step_index) do nothing
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


def run_stats(limit: int = 50) -> dict:
    """Latency + cost aggregates over the most recent `limit` completed runs —
    feeds the dashboard's stat row. Percentiles, not the mean: LLM latency is
    right-skewed, so p50/p95 describe an actual run and the mean doesn't (ADR-0014)."""
    with connect() as conn:
        row = conn.execute(
            """
            with recent as (
                select elapsed_s, cost_usd, cache_hit
                from incident_runs
                where status in ('resolved', 'rejected', 'escalated', 'awaiting-approval')
                order by created_at desc
                limit %s
            )
            select
                count(*),
                percentile_cont(0.5)  within group (order by elapsed_s),
                percentile_cont(0.95) within group (order by elapsed_s),
                percentile_cont(0.5)  within group (order by cost_usd),
                avg(cost_usd),
                avg(case when cache_hit then 1.0 else 0.0 end)
            from recent
            """,
            (limit,),
        ).fetchone()
    n = row[0] or 0
    return {
        "n": n,
        "latency_p50_s": round(float(row[1]), 1) if row[1] is not None else None,
        "latency_p95_s": round(float(row[2]), 1) if row[2] is not None else None,
        "cost_p50_usd": round(float(row[3]), 6) if row[3] is not None else None,
        "cost_mean_usd": round(float(row[4]), 6) if row[4] is not None else None,
        "cache_hit_rate": round(float(row[5]), 3) if row[5] is not None else None,
    }


@dataclass
class ScoreRecord:
    name: str
    value_num: float | None
    value_text: str | None
    data_type: str
    comment: str | None
    created_at: datetime

    @property
    def value(self) -> float | str:
        return self.value_text if self.value_text is not None else float(self.value_num or 0.0)


def record_online_scores(run_id: str, scores: list) -> None:
    """Upsert the reference-free online scores for one run (ADR-0018, migration
    0013). One row per `(run_id, name)`: a re-score replaces the value. Each
    `scores` item is a `core.scoring.Score` (name / data_type / value / comment)."""
    if not scores:
        return
    with connect() as conn, conn.transaction():
        for s in scores:
            is_text = s.data_type == "CATEGORICAL"
            conn.execute(
                """
                insert into online_scores
                    (run_id, name, value_num, value_text, data_type, comment)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (run_id, name) do update set
                    value_num = excluded.value_num, value_text = excluded.value_text,
                    data_type = excluded.data_type, comment = excluded.comment,
                    created_at = now()
                """,
                (
                    run_id,
                    s.name,
                    None if is_text else float(s.value),
                    s.value if is_text else None,
                    s.data_type,
                    s.comment,
                ),
            )


def get_scores(run_id: str) -> list[ScoreRecord]:
    """The online scores recorded for one run, if any. Best-effort — a missing
    table reads as 'no scores' (safe to ship ahead of migration 0013)."""
    try:
        with connect() as conn:
            rows = conn.execute(
                "select name, value_num, value_text, data_type, comment, created_at "
                "from online_scores where run_id = %s order by name",
                (run_id,),
            ).fetchall()
    except Exception:  # noqa: BLE001 - best-effort read
        return []
    return [ScoreRecord(*r) for r in rows]


def list_recent_scores(limit: int = 20) -> dict[str, list[ScoreRecord]]:
    """The most recently scored runs → their scores, newest run first. Feeds
    `runbook scores` (the flywheel on-ramp)."""
    with connect() as conn:
        rows = conn.execute(
            """
            with recent as (
                select run_id, max(created_at) as scored_at
                from online_scores
                group by run_id
                order by scored_at desc
                limit %s
            )
            select s.run_id, s.name, s.value_num, s.value_text, s.data_type, s.comment,
                   s.created_at, recent.scored_at
            from online_scores s
            join recent on recent.run_id = s.run_id
            order by recent.scored_at desc, s.name
            """,
            (limit,),
        ).fetchall()
    out: dict[str, list[ScoreRecord]] = {}
    for r in rows:
        out.setdefault(r[0], []).append(ScoreRecord(*r[1:7]))
    return out


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
