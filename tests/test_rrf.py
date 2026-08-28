"""Reciprocal Rank Fusion — pure function, no DB or models."""

from runbook.rag import rrf_fuse


def test_single_list_preserves_order():
    fused = rrf_fuse([[10, 20, 30]])
    assert [doc_id for doc_id, _ in fused] == [10, 20, 30]


def test_agreement_across_lists_wins():
    # A is rank-1 in BOTH lists; X is rank-0 in one list and absent from the other.
    # Two mid-pack agreements (2/61) beat a single top hit (1/60) — this is the
    # point of RRF for hybrid search.
    fused = dict(rrf_fuse([[10, 1], [20, 1]]))
    assert fused[1] > fused[10]
    assert fused[1] > fused[20]


def test_absent_from_a_list_contributes_nothing():
    fused = dict(rrf_fuse([[1, 2], [1]]))
    # 1 appears in both, 2 only in the first
    assert fused[1] > fused[2]


def test_larger_k_rrf_flattens_rank_weight():
    top_gap_small_k = dict(rrf_fuse([[1, 2]], k_rrf=1))
    top_gap_large_k = dict(rrf_fuse([[1, 2]], k_rrf=1000))
    assert (top_gap_small_k[1] - top_gap_small_k[2]) > (top_gap_large_k[1] - top_gap_large_k[2])


def test_stable_tiebreak_by_id():
    fused = rrf_fuse([[5, 3]])  # scores: 5→1/60, 3→1/61
    ids = [doc_id for doc_id, _ in fused]
    assert ids == [5, 3]
