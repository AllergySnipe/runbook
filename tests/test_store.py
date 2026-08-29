"""`compute_status` — the run lifecycle, as a pure function. This is where the
S1 guarantee is pinned: a `needs-approval` run is never `resolved` until every
state-changing step is approved. No DB (the SQL shell is covered by the
skipped-without-a-DB integration test).
"""

from __future__ import annotations

import pytest

from runbook.core.store import compute_status

CASES = [
    # disposition, approval states, expected status
    (None, [], "short-circuited"),
    ("auto", [], "resolved"),
    ("escalate", [], "escalated"),
    ("needs-approval", ["pending"], "awaiting-approval"),
    ("needs-approval", ["pending", "pending"], "awaiting-approval"),
    ("needs-approval", ["approved", "pending"], "awaiting-approval"),
    ("needs-approval", ["approved"], "resolved"),
    ("needs-approval", ["approved", "approved"], "resolved"),
    ("needs-approval", ["rejected"], "rejected"),
    ("needs-approval", ["approved", "rejected"], "rejected"),
    ("needs-approval", ["pending", "rejected"], "rejected"),
    ("needs-approval", [], "awaiting-approval"),  # defensive: no rows yet
]


@pytest.mark.parametrize("disposition, states, expected", CASES)
def test_compute_status(disposition, states, expected):
    assert compute_status(disposition, states) == expected


def test_rejection_is_sticky_even_with_other_approvals():
    assert compute_status("needs-approval", ["approved", "approved", "rejected"]) == "rejected"


def test_all_approved_only_counts_when_there_are_rows():
    # `all([])` is True — the guard stops an empty list reading as "resolved"
    assert compute_status("needs-approval", []) == "awaiting-approval"
