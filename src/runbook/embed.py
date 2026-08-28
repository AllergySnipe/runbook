"""The single embedding call site (ADR-0002).

Local `fastembed` model, loaded lazily and reused. Corpus chunks are embedded as
passages; queries go through `embed_query`, which applies BGE's retrieval
instruction. Vectors come back as plain lists so callers (and tests) don't need
numpy.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .config import get_settings

_model = None  # fastembed.TextEmbedding, lazy

# BGE v1.5 recommends this instruction on the *query* side of query→passage retrieval
# (model card). fastembed does not apply it automatically for bge-small, so we do.
_BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _model = TextEmbedding(model_name=get_settings().embedding_model)
    return _model


def embed_passages(texts: Sequence[str]) -> list[list[float]]:
    """Embed corpus chunks (no instruction prefix)."""
    return [v.tolist() for v in _get_model().embed(list(texts))]


def embed_query(text: str) -> list[float]:
    """Embed a search query. For BGE models the retrieval instruction is prepended."""
    if "bge" in get_settings().embedding_model.lower():
        text = _BGE_QUERY_INSTRUCTION + text
    return embed_passages([text])[0]


def to_pgvector(vec: Iterable[float]) -> str:
    """pgvector text literal, e.g. '[0.1,0.2,...]'. Bind with `%s::vector`."""
    return "[" + ",".join(f"{x:.7g}" for x in vec) + "]"


def backfill(*, only_missing: bool = True, batch_size: int = 256) -> int:
    """Embed `documents.chunk_text` into `documents.embedding`. Returns rows written."""
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
