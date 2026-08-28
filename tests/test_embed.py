"""Embedding tests. `test_embed_*` download the fastembed model on first run (~90 MB)."""

from runbook.embed import embed_passages, embed_query, to_pgvector


def test_to_pgvector_literal():
    assert to_pgvector([0.5, -1.0, 2.0]) == "[0.5,-1,2]"


def test_embed_passages_shape_and_determinism():
    a = embed_passages(["database connection pool exhausted", "redis eviction"])
    assert len(a) == 2
    assert all(len(v) == 384 for v in a)
    b = embed_passages(["database connection pool exhausted"])
    assert b[0] == a[0]  # deterministic


def test_query_and_passage_embeddings_differ():
    q = embed_query("why is paymentsvc latency high")
    p = embed_passages(["why is paymentsvc latency high"])[0]
    assert len(q) == 384
    assert q != p  # BGE query instruction changes the vector
