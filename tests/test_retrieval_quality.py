"""Retrieval-quality gate for the hybrid-search slice.

Runs the real `retrieve()` path against Neon, so it needs `DATABASE_URL` and
downloads the embedding + rerank models on first run. Skipped otherwise (CI
without a DB, offline unit runs).

Each case is a paraphrased alert — deliberately *not* the runbook's title — and
must surface its own runbook in the top 3 (`SPEC.md`: hit@3 ≥ 0.85; synthetic
target 6/6).
"""

import os

import pytest


def _has_db() -> bool:
    try:
        from runbook.config import get_settings

        return bool(get_settings().database_url)
    except Exception:  # noqa: BLE001 - any config failure means "no DB, skip"
        return False


pytestmark = pytest.mark.skipif(
    not _has_db(), reason="needs a configured database_url (real Neon retrieval)"
)

# (paraphrased alert, expected runbook filename)
CASES = [
    (
        (
            "checkout is throwing 5xx on POST /charges, our external card processor "
            "looks slow and customers can't complete payments"
        ),
        "acquirer-gw-timeouts.md",
    ),
    (
        (
            "right after the last deploy paymentsvc availability tanked, queries on the "
            "charges table seem stuck waiting on a lock from a schema change"
        ),
        "bad-migration-table-lock.md",
    ),
    (
        (
            "p99 latency spiked to several seconds but the database CPU and load are "
            "normal, looks like requests are waiting for a free connection"
        ),
        "db-connection-pool-exhaustion.md",
    ),
    (
        (
            "latency rising in bursts with no traffic change and no deploy, cfs "
            "throttled periods are high but cpu usage is only moderate"
        ),
        "noisy-neighbour-cpu-throttling.md",
    ),
    (
        (
            "charges are succeeding but the ledger and merchant webhooks are delayed, "
            "consumer group lag on the events queue keeps climbing"
        ),
        "payments-events-consumer-lag.md",
    ),
    (
        (
            "idempotency key lookups are missing and we're at risk of double-charging "
            "customers on retries, redis is under memory pressure and evicting keys"
        ),
        "redis-eviction-idempotency.md",
    ),
]


@pytest.mark.parametrize("query,expected", CASES, ids=[c[1] for c in CASES])
def test_hit_at_3(query, expected):
    from runbook.rag import retrieve

    hits = retrieve(query, k=3, mode="hybrid")
    got = [os.path.basename(h.path) for h in hits if h.path]
    assert expected in got, f"{expected} not in top-3 {got} for {query!r}"
