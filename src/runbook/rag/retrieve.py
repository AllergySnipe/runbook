"""Hybrid retrieval over `documents` (ADR-0003).

Pipeline for `mode="hybrid"`:

    query
      ├─ vector search   (embedding <=> qvec, HNSW)      → ranked ids
      └─ full-text search (chunk_tsv @@ query, GIN)      → ranked ids
      → Reciprocal Rank Fusion                           → fused ids
      → hydrate top `retrieve_candidates` rows
      → (optional) cross-encoder rerank                  → re-sorted
      → top k

`mode="vector"` / `"text"` run a single leg (used by the CLI and ADR-0003 to show
what hybrid buys over pure vector). All DB access is sync — an async wrapper can
land with the tool-loop slice that needs it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import psycopg

from ..config import get_settings
from ..db import connect
from ..embed import embed_query, to_pgvector

Mode = Literal["hybrid", "vector", "text"]

RRF_K = 60  # standard constant; dampens the weight of top ranks so lower ranks still count


@dataclass
class RetrievedChunk:
    id: int
    title: str
    url: str | None
    source: str
    origin: str
    path: str | None  # provenance: repo-relative file path from ingest metadata
    heading_path: list[str]
    chunk_text: str
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def heading_display(self) -> str:
        return " › ".join(self.heading_path) if self.heading_path else "—"


def rrf_fuse(rankings: list[list[int]], k_rrf: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion.

    `rankings` is a list of ranked id-lists (rank 0 = best in that list). An id's
    fused score is the sum over lists of `1 / (k_rrf + rank)`; absent from a list
    contributes nothing. Returns `(id, score)` sorted by score descending, then id
    ascending for a stable order. Uses only rank position, never the raw distances
    / ts_rank scores — which live on different scales and don't normalise cleanly.
    """
    scores: dict[int, float] = {}
    for ranked in rankings:
        for rank, doc_id in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k_rrf + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def _vector_search(conn: psycopg.Connection, query: str, limit: int) -> list[tuple[int, float]]:
    qvec = to_pgvector(embed_query(query))
    rows = conn.execute(
        """
        select id, embedding <=> %s::vector as distance
        from documents
        where embedding is not null
        order by distance
        limit %s
        """,
        (qvec, limit),
    ).fetchall()
    return [(r[0], float(r[1])) for r in rows]


def _text_search(conn: psycopg.Connection, query: str, limit: int) -> list[tuple[int, float]]:
    rows = conn.execute(
        """
        select d.id, ts_rank_cd(d.chunk_tsv, q) as rank
        from documents d, websearch_to_tsquery('english', %s) q
        where d.chunk_tsv @@ q
        order by rank desc
        limit %s
        """,
        (query, limit),
    ).fetchall()
    return [(r[0], float(r[1])) for r in rows]


def _hydrate(conn: psycopg.Connection, ids: list[int]) -> dict[int, RetrievedChunk]:
    if not ids:
        return {}
    rows = conn.execute(
        """
        select id, title, url, source, origin, chunk_text, metadata
        from documents
        where id = any(%s)
        """,
        (ids,),
    ).fetchall()
    out: dict[int, RetrievedChunk] = {}
    for rid, title, url, source, origin, chunk_text, metadata in rows:
        meta = metadata or {}
        out[rid] = RetrievedChunk(
            id=rid,
            title=title,
            url=url,
            source=source,
            origin=origin,
            path=meta.get("path"),
            heading_path=list(meta.get("heading_path") or []),
            chunk_text=chunk_text,
        )
    return out


def retrieve(
    query: str,
    k: int = 5,
    *,
    mode: Mode = "hybrid",
    rerank: bool | None = None,
) -> list[RetrievedChunk]:
    """Return the top `k` chunks for `query`.

    `rerank=None` follows `settings.rerank_enabled`; pass a bool to force it.
    Rerank is skipped for single-leg modes only if explicitly disabled — it still
    helps there.
    """
    settings = get_settings()
    depth = settings.retrieve_candidates
    do_rerank = settings.rerank_enabled if rerank is None else rerank

    with connect() as conn:
        legs: list[list[int]] = []
        raw: dict[str, dict[int, float]] = {}
        if mode in ("hybrid", "vector"):
            vec = _vector_search(conn, query, depth)
            raw["vector"] = dict(vec)
            legs.append([doc_id for doc_id, _ in vec])
        if mode in ("hybrid", "text"):
            txt = _text_search(conn, query, depth)
            raw["text"] = dict(txt)
            legs.append([doc_id for doc_id, _ in txt])

        fused = rrf_fuse(legs)
        candidate_ids = [doc_id for doc_id, _ in fused[:depth]]
        hydrated = _hydrate(conn, candidate_ids)

    chunks: list[RetrievedChunk] = []
    fused_scores = dict(fused)
    for doc_id in candidate_ids:
        chunk = hydrated.get(doc_id)
        if chunk is None:
            continue
        chunk.scores["rrf"] = fused_scores[doc_id]
        if "vector" in raw and doc_id in raw["vector"]:
            chunk.scores["vector_distance"] = raw["vector"][doc_id]
        if "text" in raw and doc_id in raw["text"]:
            chunk.scores["text_rank"] = raw["text"][doc_id]
        chunks.append(chunk)

    if do_rerank and chunks:
        from .rerank import rerank_chunks

        chunks = rerank_chunks(query, chunks)

    return chunks[:k]
