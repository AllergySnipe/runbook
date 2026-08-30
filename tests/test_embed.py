"""Embedding tests.

`test_to_pgvector_literal` is pure and always runs. The live tests hit the Jina
API (ADR-0013) and skip without a real `JINA_API_KEY` — same pattern as the
retrieval-quality gate's `DATABASE_URL` skip.
"""

import os

import pytest

from runbook.embed import embed_passages, embed_query, to_pgvector

_LIVE = (
    bool(os.environ.get("JINA_API_KEY", "")) and os.environ["JINA_API_KEY"] != "test-key-not-real"
)
live_only = pytest.mark.skipif(not _LIVE, reason="needs a real JINA_API_KEY (live embedding call)")


def test_to_pgvector_literal():
    assert to_pgvector([0.5, -1.0, 2.0]) == "[0.5,-1,2]"


@live_only
def test_embed_passages_shape_and_stability():
    a = embed_passages(["database connection pool exhausted", "redis eviction"])
    assert len(a) == 2
    assert all(len(v) == 1024 for v in a)
    # a hosted model is not bit-deterministic across calls; the same text should
    # still come back near-identical (cosine ~1), which is all retrieval needs.
    b = embed_passages(["database connection pool exhausted"])[0]
    cos = sum(x * y for x, y in zip(a[0], b, strict=True))  # both L2-normalised
    assert cos > 0.999


@live_only
def test_query_and_passage_embeddings_differ():
    q = embed_query("why is paymentsvc latency high")
    p = embed_passages(["why is paymentsvc latency high"])[0]
    assert len(q) == 1024
    assert q != p  # the retrieval.query vs retrieval.passage adapter changes the vector
