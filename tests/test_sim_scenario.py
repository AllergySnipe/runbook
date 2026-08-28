"""Deterministic tests for scenario loading and the frozen-world accessors."""

import pytest

from runbook.sim import list_scenarios, load_scenario

NAME = "db-connection-pool-exhaustion"


def test_scenario_is_listed_and_loads():
    assert NAME in list_scenarios()
    s = load_scenario(NAME)
    assert s.service == "paymentsvc"
    assert s.alert == "PaymentsvcP99LatencyHigh"
    assert s.expected_runbook == "db-connection-pool-exhaustion.md"
    lo, hi = s.incident_window
    assert lo < s.anchor < hi


def test_unknown_scenario_raises_with_a_hint():
    with pytest.raises(FileNotFoundError) as exc:
        load_scenario("does-not-exist")
    assert NAME in str(exc.value)  # the message lists the known ones


def test_metric_series_split_by_label():
    s = load_scenario(NAME)
    series = s.metric_series("paymentsvc_request_duration_seconds")
    quantiles = sorted(sr.labels["quantile"] for sr in series)
    assert quantiles == ["p50", "p95", "p99"]


def test_log_stream_is_deterministic_ordered_and_windowed():
    s = load_scenario(NAME)
    a = [ln.render() for ln in s.log_lines()]
    b = [ln.render() for ln in s.log_lines()]
    assert a == b and a  # identical across calls, non-empty
    lines = s.log_lines()
    assert [ln.ts for ln in lines] == sorted(ln.ts for ln in lines)
    lo, hi = s.incident_window
    assert all(lo <= ln.ts <= hi for ln in lines)
    assert {ln.source for ln in lines} == {"signal", "noise"}


def test_deploys_sorted_oldest_first():
    s = load_scenario(NAME)
    ds = s.deploys()
    assert [d.at for d in ds] == sorted(d.at for d in ds)
    assert any(d.migration for d in ds)  # the old index migration is in history
