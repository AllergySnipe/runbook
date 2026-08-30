"""Incident memory (`core/memory.py`) — the parts that don't need a database.

The two gates are the S-of-the-slice: a retrieved memory must clear the
similarity *floor* (below it the loop sees nothing, not a weak match), and a
store must clear the near-duplicate check the other way (a recurring page must
not fill memory with clones). Plus the eligible-status guard and the
`OutcomeResult` messaging.
"""

from __future__ import annotations

import pytest

from runbook.core.memory import (
    _ELIGIBLE_STATUSES,
    OutcomeResult,
    _is_near_duplicate,
    _passes_floor,
)

FLOOR = 0.88
DEDUPE = 0.97


@pytest.mark.parametrize(
    "similarity, expected",
    [
        (1.00, True),
        (0.88, True),  # exactly on the floor
        (0.879, False),  # just below
        (0.5, False),  # an adjacent-but-different incident
    ],
)
def test_passes_floor(similarity, expected):
    assert _passes_floor(similarity, floor=FLOOR) is expected


@pytest.mark.parametrize(
    "similarity, expected",
    [
        (1.00, True),
        (0.97, True),  # exactly on the dedupe bar
        (0.969, False),
        (0.90, False),  # similar but a distinct enough incident to keep
    ],
)
def test_is_near_duplicate(similarity, expected):
    assert _is_near_duplicate(similarity, threshold=DEDUPE) is expected


def test_only_terminal_signal_states_are_eligible():
    assert _ELIGIBLE_STATUSES == {"resolved", "escalated", "rejected"}
    for bad in ("running", "awaiting-approval", "failed", "short-circuited"):
        assert bad not in _ELIGIBLE_STATUSES


def test_outcome_result_summary_lines():
    assert "#7" in OutcomeResult(status="stored", entry_id=7).summary_line()
    assert "already" in OutcomeResult(status="exists").summary_line()
    assert "#3" in OutcomeResult(status="deduped", similar_to=3).summary_line()


def test_format_memories_empty_is_blank():
    from runbook.core.loop import _format_memories

    assert _format_memories([]) == ""


def test_format_memories_frames_as_context_not_grounding():
    from runbook.core.loop import _format_memories
    from runbook.core.memory import MemoryHit

    hit = MemoryHit(
        entry_id=1,
        similarity=0.93,
        age_days=5.0,
        alert="charges 5xx-ing, acquirer slow",
        scenario="acquirer-gw-timeouts",
        actual_root_cause="acquirer-gw partial outage",
        actual_failure_mode="acquirer-gw-timeouts",
        model_root_cause="acquirer-gw degradation",
        model_was_correct=True,
    )
    block = _format_memories([hit])
    assert "not a grounding" in block or "not instructions and not a grounding source" in block
    assert "must still quote the runbook" in block
    assert "acquirer-gw partial outage" in block
    assert "<past-incidents>" in block
