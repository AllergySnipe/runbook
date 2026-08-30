"""The semantic cache (`core/cache.py`) — the parts that don't need a database.

The hit decision (`_is_hit`) is the S-of-the-slice: both the similarity gate and
the TTL must pass. The chunk (de)serialisation must round-trip so a cache hit
reconstructs the exact `RetrievedChunk` list the loop expects.
"""

from __future__ import annotations

import pytest

from runbook.core.cache import _chunk_from_json, _chunk_to_json, _is_hit
from runbook.rag import RetrievedChunk

THRESHOLD = 0.97
TTL = 3600.0


@pytest.mark.parametrize(
    "similarity, age_s, expected",
    [
        (1.00, 0.0, True),
        (0.971, 10.0, True),
        (0.97, 3600.0, True),  # both exactly on the boundary
        (0.969, 10.0, False),  # just below the similarity gate
        (0.999, 3600.1, False),  # near-identical but stale
        (0.80, 5.0, False),  # a different failure mode, fresh
    ],
)
def test_is_hit_needs_both_gates(similarity, age_s, expected):
    assert _is_hit(similarity, age_s, threshold=THRESHOLD, ttl_s=TTL) is expected


def test_chunk_json_round_trips():
    c = RetrievedChunk(
        id=42,
        title="paymentsvc — Redis eviction",
        url=None,
        source="synthetic-runbook",
        origin="paymentsvc",
        path="corpus/synthetic/paymentsvc/redis-eviction.md",
        heading_path=["Diagnosis", "Symptoms"],
        chunk_text="idempotency keys evicted; double-charge risk",
        scores={"rrf": 0.031, "rerank": 0.92},
    )
    back = _chunk_from_json(_chunk_to_json(c))
    assert back == c


def test_chunk_json_tolerates_missing_optional_fields():
    minimal = {
        "id": 1,
        "title": "t",
        "source": "s",
        "origin": "o",
        "chunk_text": "x",
    }
    back = _chunk_from_json(minimal)
    assert back.url is None and back.path is None
    assert back.heading_path == [] and back.scores == {}
