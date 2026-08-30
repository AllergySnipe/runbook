"""Incident memory — the episodic half of the flywheel (ADR-0015).

The corpus (`documents`) is *semantic* memory: general runbooks and public
postmortems, the grounding source for every remediation step (S3). This module is
*episodic* memory: **this** system's own past incidents, each with the root cause
a human confirmed after the fact (SPEC step 7). It answers a different question —
not "what is the procedure" but "how did a page like this one actually turn out
last time".

Two write disciplines, both load-bearing:

- **Append-only.** `record_outcome` only ever inserts. A human who wants to
  correct an earlier outcome adds a new row for a new run; history is never
  mutated (audit integrity, replayability).
- **Human-confirmed only.** A row lands here solely from `record_outcome`, called
  by the CLI `outcome` command / the dashboard form. The model's own
  `diagnosis.root_cause` never becomes memory on its own — that is the guard
  against feedback poisoning (the loop retrieving and reinforcing its own past
  mistakes).

`search()` runs inside `diagnose()` (via `asyncio.to_thread`) and is best-effort
in the `cache.py` mould: every DB failure is swallowed with a warning, so the
loop degrades to "no similar incidents" rather than breaking, and the module is
safe to ship ahead of migration 0010. `record_outcome()` is the opposite — a
deliberate human action — so it surfaces its failures.

Sync (psycopg), mirroring `store.py` / `cache.py`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ..config import get_settings
from ..db import connect
from ..embed import embed_query, to_pgvector

log = logging.getLogger("runbook.memory")

_ELIGIBLE_STATUSES: frozenset[str] = frozenset({"resolved", "escalated", "rejected"})


# --- records ---------------------------------------------------------------


@dataclass
class MemoryHit:
    """One past incident retrieved as context for the current alert."""

    entry_id: int
    similarity: float
    age_days: float
    alert: str
    scenario: str
    actual_root_cause: str
    actual_failure_mode: str | None
    model_root_cause: str | None
    model_was_correct: bool | None


@dataclass
class OutcomeResult:
    """What `record_outcome` did. `stored` — a new memory row; `exists` — this run
    already had a recorded outcome (no-op); `deduped` — a near-identical incident
    is already in memory, so this outcome was not added (`similar_to` names it)."""

    status: Literal["stored", "exists", "deduped"]
    entry_id: int | None = None
    similar_to: int | None = None

    def summary_line(self) -> str:
        if self.status == "stored":
            return f"recorded incident memory #{self.entry_id}"
        if self.status == "exists":
            return "this run already has a recorded outcome — nothing changed"
        return f"not stored — a near-identical incident is already in memory (#{self.similar_to})"


# --- pure logic (no DB, unit-tested) --------------------------------------


def _passes_floor(similarity: float, *, floor: float) -> bool:
    """A retrieved memory is only shown if it clears the similarity floor. The
    floor is a real gate, not a ranking: on a genuinely novel alert every
    candidate is below it and the loop sees *nothing* rather than a misleading
    weak match."""
    return similarity >= floor


def _is_near_duplicate(similarity: float, *, threshold: float) -> bool:
    """Store-time dedupe: a recurring page fires (and gets confirmed) many times.
    Without this, memory fills with near-identical rows that crowd out diversity
    in retrieval. `threshold` is tight (~0.97) — same as the semantic cache's
    'this is the same question' bar."""
    return similarity >= threshold


# --- read (hot path — never raises) --------------------------------------


def search(alert_vec: list[float], *, n: int | None = None) -> list[MemoryHit]:
    """Up to `n` past incidents most similar to this alert, each above
    `memory_similarity_floor` cosine. Newest-incident-first among equals is *not*
    guaranteed — this is ranked by similarity. Never raises."""
    s = get_settings()
    top_n = n if n is not None else s.memory_top_n
    if top_n <= 0:
        return []
    try:
        with connect() as conn:
            rows = conn.execute(
                """
                select id, alert, scenario, actual_root_cause, actual_failure_mode,
                       model_root_cause, model_was_correct,
                       1 - (embedding <=> %s::vector) as similarity,
                       extract(epoch from now() - created_at) / 86400.0 as age_days
                from incident_memory
                order by embedding <=> %s::vector
                limit %s
                """,
                (to_pgvector(alert_vec), to_pgvector(alert_vec), top_n),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - memory is best-effort context
        log.warning("memory search skipped: %s", exc)
        return []

    hits: list[MemoryHit] = []
    for r in rows:
        similarity = float(r[7])
        if not _passes_floor(similarity, floor=s.memory_similarity_floor):
            continue
        hits.append(
            MemoryHit(
                entry_id=r[0],
                similarity=similarity,
                age_days=round(float(r[8]), 1),
                alert=r[1],
                scenario=r[2],
                actual_root_cause=r[3],
                actual_failure_mode=r[4],
                model_root_cause=r[5],
                model_was_correct=r[6],
            )
        )
    return hits


# --- write (deliberate human action — surfaces failures) ----------------


def record_outcome(
    run_id: str,
    *,
    actual_root_cause: str,
    model_was_correct: bool | None,
    actual_failure_mode: str | None = None,
    by: str,
) -> OutcomeResult:
    """Store the human-confirmed outcome of a terminal run as incident memory.

    Raises `LookupError` if the run is unknown, `ValueError` if it isn't in an
    eligible terminal state (`resolved` / `escalated` / `rejected`) or the root
    cause is blank. Idempotent on `run_id` (returns `exists`); skips a store when
    a near-identical incident is already in memory (returns `deduped`)."""
    root_cause = actual_root_cause.strip()
    if not root_cause:
        raise ValueError("actual_root_cause must not be blank")
    by = by.strip() or "unknown"

    with connect() as conn, conn.transaction():
        run = conn.execute(
            "select alert, scenario, status, diagnosis from incident_runs where id = %s",
            (run_id,),
        ).fetchone()
        if run is None:
            raise LookupError(f"no run {run_id!r}")
        alert, scenario, status, diagnosis = run
        if status not in _ELIGIBLE_STATUSES:
            raise ValueError(
                f"run {run_id} is {status!r} — record an outcome only once it is "
                f"{', '.join(sorted(_ELIGIBLE_STATUSES))}"
            )

        if conn.execute("select id from incident_memory where run_id = %s", (run_id,)).fetchone():
            return OutcomeResult(status="exists")

        model_rc = (diagnosis or {}).get("root_cause") if isinstance(diagnosis, dict) else None
        alert_vec = embed_query(alert)
        qvec = to_pgvector(alert_vec)

        nearest = conn.execute(
            """
            select id, 1 - (embedding <=> %s::vector) as similarity
            from incident_memory
            order by embedding <=> %s::vector
            limit 1
            """,
            (qvec, qvec),
        ).fetchone()
        s = get_settings()
        if nearest and _is_near_duplicate(float(nearest[1]), threshold=s.memory_dedupe_threshold):
            return OutcomeResult(status="deduped", similar_to=nearest[0])

        row = conn.execute(
            """
            insert into incident_memory (
                run_id, alert, scenario, embedding, actual_root_cause,
                actual_failure_mode, model_root_cause, model_was_correct, created_by
            )
            values (%s, %s, %s, %s::vector, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                run_id,
                alert,
                scenario,
                qvec,
                root_cause,
                actual_failure_mode,
                model_rc,
                model_was_correct,
                by,
            ),
        ).fetchone()
    return OutcomeResult(status="stored", entry_id=row[0])


@dataclass
class OutcomeRecord:
    actual_root_cause: str
    actual_failure_mode: str | None
    model_was_correct: bool | None
    created_by: str
    created_at: datetime


def get_outcome(run_id: str) -> OutcomeRecord | None:
    """The recorded outcome for one run, if a human has confirmed it. Used by the
    dashboard detail view. Best-effort — a missing table reads as 'no outcome'."""
    try:
        with connect() as conn:
            row = conn.execute(
                "select actual_root_cause, actual_failure_mode, model_was_correct, "
                "created_by, created_at from incident_memory where run_id = %s",
                (run_id,),
            ).fetchone()
    except Exception as exc:  # noqa: BLE001 - best-effort read
        log.warning("outcome lookup skipped: %s", exc)
        return None
    if row is None:
        return None
    return OutcomeRecord(
        actual_root_cause=row[0],
        actual_failure_mode=row[1],
        model_was_correct=row[2],
        created_by=row[3],
        created_at=row[4],
    )
