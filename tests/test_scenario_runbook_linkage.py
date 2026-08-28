"""Each scenario's fixtures must make its runbook's Diagnosis steps *true*.

This is the high-value test for the sim: not "does query_metrics return a list"
but "if an on-call engineer runs the `db-connection-pool-exhaustion` runbook's
Diagnosis section against this scenario, do they reach that runbook's conclusion —
and *not* a different runbook's?". One test per scenario, mirroring the runbook.
"""

from runbook.tools import (
    get_recent_deploys,
    get_service_dependencies,
    query_metrics,
    search_logs,
)


def test_db_connection_pool_exhaustion():
    name = "db-connection-pool-exhaustion"
    core = {"start": "T+2m", "end": "T+20m"}  # the incident at its height

    # Runbook step 1: pool checked-out pinned at pool size = the pool is the bottleneck.
    checked_out = query_metrics(name, "paymentsvc_db_pool_checked_out", **core).series[0]
    pool_size = query_metrics(name, "paymentsvc_db_pool_size", **core).series[0]
    assert checked_out.summary.p95 >= pool_size.summary.mean * 0.98

    # Runbook: p99 latency in seconds while p50 stays near baseline (until fully drained).
    p99 = _q(name, "paymentsvc_request_duration_seconds", "p99", core)
    p50 = _q(name, "paymentsvc_request_duration_seconds", "p50", core)
    assert p99.summary.p95 > 2.0  # crosses the PaymentsvcP99LatencyHigh threshold
    assert p50.summary.p50 < 1.0

    # Runbook step 2: query duration stepped up → points at cause (1), a query regression.
    q_pre = _q(
        name, "paymentsvc_db_query_duration_seconds", "p99", {"start": "T-10m", "end": "T-9m"}
    )
    q_in = _q(name, "paymentsvc_db_query_duration_seconds", "p99", core)
    assert q_pre.summary.min < 0.1  # normal before the deploy
    assert q_in.summary.min > 0.5  # a clear step, sustained through the incident

    # Runbook: Postgres CPU / replication lag / lock counts are normal — the DB is fine.
    assert query_metrics(name, "postgres_cpu_usage_ratio", **core).series[0].summary.max < 0.6
    assert query_metrics(name, "postgres_locks_waiting", **core).series[0].summary.max < 1

    # Runbook step 4: grep for `pool timeout` to confirm.
    assert search_logs(name, "pool timeout", **core).ok

    # Runbook step 3: a paymentsvc deploy in the hour before onset implicates the change.
    deploys = get_recent_deploys(name, service="paymentsvc", start="T-1h", end="T+0").deploys
    assert deploys and not any(
        d.migration for d in deploys
    )  # a code deploy, no migration → not the lock failure mode

    # Runbook step 5 / disambiguation: acquirer-gw is healthy → this is not acquirer-gw-timeouts.
    deps = get_service_dependencies(name)
    acquirer = next(d for d in deps.upstreams if d.name == "acquirer-gw")
    assert acquirer.health == "healthy"
    assert not deps.unhealthy()


def test_acquirer_gw_timeouts():
    name = "acquirer-gw-timeouts"
    core = {"start": "T+1m", "end": "T+25m"}

    # Alert: 5xx rate on POST /charges over 2%.
    assert _s(name, "paymentsvc_http_5xx_rate", core).summary.max > 0.02

    # Runbook step 1: acquirer request duration climbing toward the client timeout.
    assert _q(name, "paymentsvc_acquirer_request_duration_seconds", "p95", core).summary.p95 > 2.0

    # Runbook step 2: retry ratio above ~0.3 => the retry storm (cause 4) is amplifying.
    assert _s(name, "paymentsvc_acquirer_retry_ratio", core).summary.mean > 0.3

    # Runbook: charge attempts flat/rising while successes drop.
    assert _s(name, "paymentsvc_charge_attempts_per_second", core).summary.trend != "falling"
    assert _s(name, "paymentsvc_charge_success_per_second", core).summary.trend == "falling"

    # Runbook step 3: no paymentsvc deploy correlates — the change is upstream.
    assert get_recent_deploys(name, service="paymentsvc", start="T-1h", end="T+0").deploys == []

    # Runbook step 5: acquirer-gw is the implicated upstream and it is degraded.
    assert any(d.name == "acquirer-gw" for d in get_service_dependencies(name).unhealthy())
    assert search_logs(name, "deadline exceeded", **core).ok


def test_bad_migration_table_lock():
    name = "bad-migration-table-lock"
    core = {"start": "T+3m", "end": "T+15m"}

    # Alert: success rate below 95%, within ~15m of a deploy.
    assert _s(name, "paymentsvc_charge_success_rate", core).summary.min < 0.95

    # Runbook step 1: the deploy just before onset shipped a migration.
    recent = get_recent_deploys(name, service="paymentsvc", start="T-15m", end="T+2m").deploys
    assert recent and recent[-1].migration and recent[-1].migrations

    # Runbook: a lock queue pile-up, and DB CPU is *low* — backends are waiting, not working.
    assert _s(name, "postgres_locks_waiting", core).summary.max > 10
    assert _s(name, "postgres_cpu_usage_ratio", core).summary.min < 0.2

    # Runbook step 2: grep for lock timeout / deadlock.
    assert search_logs(name, "lock timeout", **core).ok


def test_noisy_neighbour_cpu_throttling():
    name = "noisy-neighbour-cpu-throttling"
    core = {"start": "T+0", "end": "T+25m"}

    # Alert: CFS throttled-periods ratio over 25%...
    assert _s(name, "container_cpu_cfs_throttled_ratio", core).summary.max > 0.25
    # ...while CPU *usage* is only moderate (below the limit) — the give-away.
    usage = _s(name, "container_cpu_usage_ratio", core).summary
    assert 0.5 < usage.mean < 0.85
    # The node itself is saturated (the noisy neighbour).
    assert _s(name, "node_cpu_usage_ratio", core).summary.max > 0.85

    # Runbook: latency is bursty (sawtooth), not a smooth climb.
    p99 = _q(name, "paymentsvc_request_duration_seconds", "p99", core).summary
    assert p99.max - p99.mean > 0.3

    # Runbook step 3: nothing shipped for paymentsvc; a *neighbour* scaled up.
    assert get_recent_deploys(name, service="paymentsvc", start="T-1h", end="T+0").deploys == []
    assert any(d.service == "batch-reconciler" for d in get_recent_deploys(name).deploys)

    # Runbook step 5: expect *no* application errors — the absence is the signal.
    miss = search_logs(name, "error", **core)
    assert not miss.ok and "Absence of errors" in miss.hint
    assert search_logs(name, "throttled", **core).ok
    assert not get_service_dependencies(name).unhealthy()


def test_payments_events_consumer_lag():
    name = "payments-events-consumer-lag"
    core = {"start": "T+0", "end": "T+25m"}

    # Alert: consumer-group lag over 10k.
    assert _s(name, "payments_events_consumer_lag", core).summary.max > 10_000

    # Runbook: the pay path is HEALTHY — this is the signal that rules the other failure modes out.
    assert _s(name, "paymentsvc_charge_success_rate", core).summary.min > 0.99
    assert _s(name, "paymentsvc_http_5xx_rate", core).summary.max < 0.01

    # Runbook step 3: the lagging consumer is down / crash-looping.
    assert _s(name, "ledger_pod_restarts_total", core).summary.max >= 10
    deps = get_service_dependencies(name)
    assert {d.name for d in deps.unhealthy()} >= {"ledger", "payments-events"}

    # Runbook step 5: a downstream deploy caused it; nothing shipped for paymentsvc.
    assert get_recent_deploys(name, service="paymentsvc", start="T-1h", end="T+0").deploys == []
    assert any(d.service == "ledger" for d in get_recent_deploys(name).deploys)

    # Runbook step 4: a repeating error on the consumer (not a poison-message single offset).
    assert search_logs(name, "panic", **core).ok


def test_redis_eviction_idempotency():
    name = "redis-eviction-idempotency"
    core = {"start": "T-2m", "end": "T+22m"}

    # Alert: idempotency miss rate over 1%.
    assert _s(name, "paymentsvc_idempotency_miss_ratio", core).summary.max > 0.01

    # Runbook step 1: Redis memory pressure + eviction is the cause.
    assert _s(name, "redis_used_memory_ratio", core).summary.max > 0.95
    assert _s(name, "redis_evicted_keys_rate", core).summary.max > 0

    # Runbook step 5: duplicate charge rows — the smoking gun — while charges still succeed.
    assert _s(name, "paymentsvc_duplicate_charge_total", core).summary.max >= 1
    assert _s(name, "paymentsvc_charge_success_rate", core).summary.min > 0.99

    # Redis is the degraded dependency.
    assert any(d.name == "redis-idempotency" for d in get_service_dependencies(name).unhealthy())

    # Runbook step 3: the idempotency path is failing *open*.
    assert search_logs(name, "fail-open", **core).ok
    assert search_logs(name, "duplicate charge", **core).ok


def test_healthy_baseline_shows_no_incident():
    from runbook.sim import load_scenario

    name = "healthy"
    assert load_scenario(name).alert == ""  # no alert fires

    # Every incident indicator sits at its normal level.
    assert _s(name, "paymentsvc_http_5xx_rate").summary.max < 0.01
    assert _s(name, "paymentsvc_charge_success_rate").summary.min > 0.99
    assert _s(name, "postgres_locks_waiting").summary.max < 1
    assert _s(name, "container_cpu_cfs_throttled_ratio").summary.max < 0.1
    assert _q(name, "paymentsvc_request_duration_seconds", "p99", {}).summary.max < 1.0
    assert _s(name, "payments_events_consumer_lag").summary.max < 2000
    assert _s(name, "paymentsvc_idempotency_miss_ratio").summary.max < 0.01

    # No errors in the log stream, no degraded dependency, no deploy in the recent window.
    assert not search_logs(name, "error").ok
    assert not get_service_dependencies(name).unhealthy()
    assert get_recent_deploys(name).deploys == []


def _s(name, metric, window=None):
    """The single series for a metric that has exactly one label-set."""
    res = query_metrics(name, metric, **(window or {}))
    assert len(res.series) == 1, f"{metric}: expected one series, got {len(res.series)}"
    return res.series[0]


def _q(name, metric, quantile, window):
    for sr in query_metrics(name, metric, **window).series:
        if sr.labels.get("quantile") == quantile:
            return sr
    raise AssertionError(f"{metric}{{quantile={quantile}}} not found")
