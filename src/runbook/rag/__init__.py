"""Retrieval: given a query, return the most relevant corpus chunks.

Hybrid search (ADR-0003): pgvector cosine + Postgres full-text, fused with
Reciprocal Rank Fusion, then an optional cross-encoder rerank over the shortlist.

    from runbook.rag import retrieve
    hits = retrieve("paymentsvc 500s, db connections timing out", k=3)
"""

from .retrieve import RetrievedChunk, retrieve, rrf_fuse

__all__ = ["RetrievedChunk", "retrieve", "rrf_fuse"]
