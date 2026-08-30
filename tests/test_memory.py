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
