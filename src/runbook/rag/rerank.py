"""Cross-encoder rerank pass (ADR-0003 → ADR-0013).

The bi-encoder that powers vector search encodes the query and each chunk
*separately*, so its similarity score never sees the two together. A cross-encoder
feeds `(query, chunk)` through the model as one input and outputs a single
relevance score — much sharper, but it's one comparison per candidate, so it only
runs over the fused shortlist, never the corpus.

Hosted model via Jina (`jina.py`) — see ADR-0013 for why the local ONNX model
moved off the box.
"""

from __future__ import annotations

from .. import jina
from .retrieve import RetrievedChunk


def rerank_chunks(query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Re-score `chunks` against `query` with the cross-encoder and return them
    sorted best-first. Writes each score to `chunk.scores["rerank"]`."""
    for idx, score in jina.rerank(query, [c.chunk_text for c in chunks]):
        chunks[idx].scores["rerank"] = score
    return sorted(chunks, key=lambda c: c.scores["rerank"], reverse=True)
