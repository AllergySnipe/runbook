"""Deterministic tests for the read-only tool layer — no DB, no model calls."""

from runbook.tools import (
    TOOLS,
    get_recent_deploys,
    get_service_dependencies,
    query_metrics,
    search_logs,
)

NAME = "db-connection-pool-exhaustion"


def test_allowlist_is_exactly_the_four_read_only_tools():
    assert set(TOOLS) == {
        "query_metrics",
        "search_logs",
        "get_recent_deploys",
        "get_service_dependencies",
    }


def test_query_metrics_returns_series_with_summary():
    r = query_metrics(NAME, "paymentsvc_db_pool_checked_out")
    assert r.ok and len(r.series) == 1
    assert r.series[0].summary.max > 0


def test_query_metrics_unknown_metric_explains():
    r = query_metrics(NAME, "disk_io")  # matches nothing
    assert not r.ok
    assert r.error and "disk_io" in r.error
    assert "paymentsvc_db_pool_size" in r.available


def test_query_metrics_resolves_a_unique_substring():
    r = query_metrics(NAME, "locks_waiting")
    assert r.ok
    assert r.series[0].name == "postgres_locks_waiting"


def test_search_logs_finds_signal_and_filters_by_level():
    hit = search_logs(NAME, "pool timeout")
    assert hit.ok and all("pool timeout" in m.line.lower() for m in hit.matches)
    assert hit.total_scanned > len(hit.matches)  # noise was scanned too

    errors_only = search_logs(NAME, "pool timeout", level="ERROR")
    assert errors_only.ok and {m.level for m in errors_only.matches} == {"ERROR"}


def test_search_logs_miss_returns_a_hint_not_an_exception():
    miss = search_logs(NAME, "kernel panic zzz")
    assert not miss.ok
    assert miss.matches == []
    assert "nothing matched" in miss.hint


def test_search_logs_limit_truncates():
    r = search_logs(NAME, "POST /charges", limit=3)
    assert len(r.matches) == 3 and r.truncated


def test_get_recent_deploys_widens_to_catch_pre_onset_deploy():
    r = get_recent_deploys(NAME)
    versions = [d.version for d in r.deploys]
    assert "2026.8.28-4f9c1a2" in versions  # the T-9m deploy
    assert "2026.8.25-9b2e7c1" not in versions  # T-3d, outside the widened window

    filtered = get_recent_deploys(NAME, service="ledger")
    assert filtered.deploys == []


def test_get_service_dependencies_default_and_unknown():
    g = get_service_dependencies(NAME)
    assert g.service == "paymentsvc"
    assert {d.name for d in g.upstreams} >= {"postgres-primary", "acquirer-gw"}

    other = get_service_dependencies(NAME, service="checkout-web")
    assert other.service == "checkout-web" and not other.upstreams
