"""Deterministic tests for the synthetic incident clock — no DB, no wall clock."""

from datetime import UTC, datetime, timedelta

import pytest

from runbook.sim.clock import parse_duration, parse_offset, parse_time, parse_window

ANCHOR = datetime(2026, 8, 28, 14, 0, tzinfo=UTC)


def test_parse_offset_units_and_sign():
    assert parse_offset("T+0") == timedelta(0)
    assert parse_offset("T+90s") == timedelta(seconds=90)
    assert parse_offset("T+7m") == timedelta(minutes=7)
    assert parse_offset("T-10m") == timedelta(minutes=-10)
    assert parse_offset("T+1h30m") == timedelta(hours=1, minutes=30)


def test_parse_offset_rejects_garbage():
    for bad in ("7m", "T+", "T*3m", "T+3x"):
        with pytest.raises(ValueError):
            parse_offset(bad)


def test_parse_duration():
    assert parse_duration("5m") == timedelta(minutes=5)
    assert parse_duration("1h30m") == timedelta(hours=1, minutes=30)
    assert parse_duration(45) == timedelta(seconds=45)


def test_parse_time_relative_and_absolute():
    assert parse_time("T+5m", ANCHOR) == ANCHOR + timedelta(minutes=5)
    assert parse_time("2026-08-28T14:07:00Z", ANCHOR) == ANCHOR + timedelta(minutes=7)
    # a naive datetime is assumed to already be UTC
    naive = datetime(2026, 8, 28, 14, 0)  # noqa: DTZ001 - the point of the test
    assert parse_time(naive, ANCHOR) == ANCHOR


def test_parse_time_none_passes_through():
    assert parse_time(None, ANCHOR) is None


def test_parse_window_defaults_and_validation():
    default = (ANCHOR - timedelta(minutes=10), ANCHOR + timedelta(minutes=30))
    assert parse_window(None, None, ANCHOR, default) == default
    lo, hi = parse_window("T+0", "T+5m", ANCHOR, default)
    assert (lo, hi) == (ANCHOR, ANCHOR + timedelta(minutes=5))
    with pytest.raises(ValueError):
        parse_window("T+10m", "T+5m", ANCHOR, default)
