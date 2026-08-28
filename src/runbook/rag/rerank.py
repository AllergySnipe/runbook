"""Cross-encoder rerank pass (ADR-0003).

The bi-encoder (BGE) that powers vector search encodes the query and each chunk
*separately*, so its similarity score never sees the two together. A cross-encoder
feeds `(query, chunk)` through the model as one input and outputs a single
relevance score — much sharper, but it's one model call per candidate, so it only
runs over the fused shortlist, never the corpus.

Local ONNX model via `fastembed` (same rationale as ADR-0002: no API key, offline,
baked into the Docker image). Lazy singleton, mirroring `embed.py`.
"""

from __future__ import annotations

from .retrieve import RetrievedChunk

_encoder = None  # fastembed TextCrossEncoder, lazy


def _get_encoder():
    global _encoder
    if _encoder is None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        from ..config import get_settings

        _encoder = TextCrossEncoder(model_name=get_settings().rerank_model)
    return _encoder


def rerank_chunks(query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Re-score `chunks` against `query` with the cross-encoder and return them
    sorted best-first. Writes each score to `chunk.scores["rerank"]`."""
    scores = list(_get_encoder().rerank(query, [c.chunk_text for c in chunks]))
    for chunk, score in zip(chunks, scores, strict=True):
        chunk.scores["rerank"] = float(score)
    return sorted(chunks, key=lambda c: c.scores["rerank"], reverse=True)
