"""Semantic cache for the incident-loop prefix (ADR-0014).

Bursty on-call alerts repeat: the same page fires many times during one incident,
with drifting text (current value, timestamps). Redoing triage + hybrid retrieval
for each near-duplicate is waste. This cache keys on an embedding of the alert; a
prior alert within `cache_similarity_threshold` cosine **and** `cache_ttl_s`
seconds is a hit, and its triage verdict + retrieved runbook set are reused. The
investigation loop still runs fresh against the (sim) environment.

Two design choices worth stating:

- **The gate is deliberately tight (~0.97).** A false negative just repeats work;
  a false positive serves the wrong runbook for a genuinely different incident.
  Genuinely-different failure modes embed at ~0.75–0.88 similarity; true
  restatements at ~0.97–1.00. We accept many false negatives to push false
  positives near zero.
- **The prefix is cached, never the diagnosis.** The environment moves between two
  fires of the same alert, and an approval-gated system must not serve last hour's
  remediation for this hour's incident.

Sync (psycopg), mirroring `store.py`; reached from `core/loop.py` via
`asyncio.to_thread`. Every DB failure here is swallowed with a warning — the cache
is an accelerator, never load-bearing. This also makes the deploy safe before
migration 0008 lands: lookups/stores no-op until the table exists.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from ..config import get_settings
from ..db import connect
from ..embed import to_pgvector
from ..rag import RetrievedChunk
from .triage import TriageResult

log = logging.getLogger("runbook.cache")


@dataclass
class CacheHit:
    entry_id: int
    similarity: float
    age_s: float
    triage: TriageResult
    retrieved: list[RetrievedChunk]


def _is_hit(similarity: float, age_s: float, *, threshold: float, ttl_s: float) -> bool:
    """The hit decision, pure and unit-tested. Both gates must pass."""
    return similarity >= threshold and age_s <= ttl_s


def _chunk_to_json(c: RetrievedChunk) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "url": c.url,
        "source": c.source,
        "origin": c.origin,
        "path": c.path,
        "heading_path": c.heading_path,
        "chunk_text": c.chunk_text,
        "scores": c.scores,
    }


def _chunk_from_json(d: dict) -> RetrievedChunk:
    return RetrievedChunk(
        id=d["id"],
        title=d["title"],
        url=d.get("url"),
        source=d["source"],
        origin=d["origin"],
        path=d.get("path"),
        heading_path=list(d.get("heading_path") or []),
        chunk_text=d["chunk_text"],
        scores=dict(d.get("scores") or {}),
    )


def lookup(alert_vec: list[float]) -> CacheHit | None:
    """Nearest prior alert within the TTL window; returns a `CacheHit` if it also
    clears the similarity gate, else `None`. Never raises."""
    s = get_settings()
    try:
        with connect() as conn:
            row = conn.execute(
                """
                select id, triage, retrieved, created_at,
                       1 - (embedding <=> %s::vector) as similarity,
                       extract(epoch from now() - created_at) as age_s
                from alert_cache
                where created_at > now() - make_interval(secs => %s)
                order by embedding <=> %s::vector
                limit 1
                """,
                (to_pgvector(alert_vec), s.cache_ttl_s, to_pgvector(alert_vec)),
            ).fetchone()
    except Exception as exc:  # noqa: BLE001 - cache is best-effort
        log.warning("cache lookup skipped: %s", exc)
        return None

    if row is None:
        return None
    entry_id, triage_json, retrieved_json, _created_at, similarity, age_s = row
    similarity, age_s = float(similarity), float(age_s)
    if not _is_hit(similarity, age_s, threshold=s.cache_similarity_threshold, ttl_s=s.cache_ttl_s):
        return None
    try:
        tri = TriageResult.model_validate(triage_json)
        chunks = [_chunk_from_json(d) for d in retrieved_json]
    except Exception as exc:  # noqa: BLE001 - a malformed row is a miss, not a crash
        log.warning("cache hit discarded (unreadable payload): %s", exc)
        return None
    return CacheHit(entry_id, similarity, age_s, tri, chunks)


def store(
    alert_norm: str,
    alert_vec: list[float],
    *,
    triage: TriageResult,
    retrieved: list[RetrievedChunk],
    run_id: str | None = None,
) -> None:
    """Record the prefix this alert produced, for future near-duplicates. Never
    raises — a failed cache write must not fail a successful diagnosis."""
    try:
        with connect() as conn, conn.transaction():
            conn.execute(
                """
                insert into alert_cache (alert_norm, embedding, triage, retrieved, run_id)
                values (%s, %s::vector, %s::jsonb, %s::jsonb, %s)
                """,
                (
                    alert_norm,
                    to_pgvector(alert_vec),
                    triage.model_dump_json(),
                    json.dumps([_chunk_to_json(c) for c in retrieved]),
                    run_id,
                ),
            )
    except Exception as exc:  # noqa: BLE001 - cache is best-effort
        log.warning("cache store skipped: %s", exc)
