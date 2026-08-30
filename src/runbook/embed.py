"""The single embedding call site (ADR-0002 → ADR-0013).

Hosted model via Jina (`jina.py`). Corpus chunks are embedded with the
`retrieval.passage` task adapter; queries with `retrieval.query` — asymmetric
search, the model encodes a short question differently from a long document.
Vectors come back as plain lists so callers (and tests) don't need numpy.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from . import jina


def embed_passages(texts: Sequence[str]) -> list[list[float]]:
    """Embed corpus chunks (indexing side)."""
    return jina.embed(list(texts), task="retrieval.passage")


def embed_query(text: str) -> list[float]:
    """Embed a search query (query side of asymmetric retrieval)."""
    return jina.embed([text], task="retrieval.query")[0]


def to_pgvector(vec: Iterable[float]) -> str:
    """pgvector text literal, e.g. '[0.1,0.2,...]'. Bind with `%s::vector`."""
    return "[" + ",".join(f"{x:.7g}" for x in vec) + "]"


def backfill(*, only_missing: bool = True, batch_size: int = 96) -> int:
    """Embed `documents.chunk_text` into `documents.embedding`. Returns rows written.

    Re-run after every `runbook ingest`, and after any `embedding_model` change
    (with `only_missing=False` — the whole corpus must share one model)."""
    from .db import connect

    query = "select id, chunk_text from documents order by id"
    if only_missing:
        query = "select id, chunk_text from documents where embedding is null order by id"
    written = 0
    with connect(direct=True) as conn:
        conn.autocommit = True
        rows = conn.execute(query).fetchall()
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            vecs = embed_passages([text for _, text in batch])
            with conn.transaction():
                conn.cursor().executemany(
                    "update documents set embedding = %s::vector where id = %s",
                    [(to_pgvector(v), doc_id) for (doc_id, _), v in zip(batch, vecs, strict=True)],
                )
            written += len(batch)
    return written
