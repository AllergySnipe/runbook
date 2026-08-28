"""Deterministic tests for compact-spec → time-series expansion."""

from datetime import UTC, datetime, timedelta

from runbook.sim.series import SeriesSpec, expand_series

ANCHOR = datetime(2026, 8, 28, 14, 0, tzinfo=UTC)
WINDOW = (ANCHOR - timedelta(minutes=10), ANCHOR + timedelta(minutes=30))


def _spec(raw: dict) -> SeriesSpec:
    return SeriesSpec.from_dict({"unit": "x", **raw}, ANCHOR)


def test_flat_series_is_flat():
    s = expand_series(_spec({"name": "m", "baseline": 3.0}), WINDOW)
    assert {p.value for p in s.points} == {3.0}
    assert s.summary.trend == "flat"
    assert s.summary.min == s.summary.max == 3.0


def test_step_change_has_two_levels():
    s = expand_series(
        _spec(
            {
                "name": "m",
                "baseline": 0.05,
                "segments": [{"at": "T+2m", "to": 0.8, "shape": "step"}],
            }
        ),
        WINDOW,
    )
    before = [p.value for p in s.points if p.ts < ANCHOR + timedelta(minutes=2)]
    after = [p.value for p in s.points if p.ts >= ANCHOR + timedelta(minutes=2)]
    assert max(before) < 0.1 < min(after)
    assert s.summary.max == 0.8


def test_ramp_is_monotonic_between_endpoints():
    s = expand_series(
        _spec(
            {
                "name": "m",
                "baseline": 1.0,
                "segments": [{"at": "T+0", "to": 5.0, "shape": "ramp", "over": "4m"}],
            }
        ),
        (ANCHOR, ANCHOR + timedelta(minutes=6)),
    )
    ramp = [p.value for p in s.points if p.ts <= ANCHOR + timedelta(minutes=4)]
    assert ramp == sorted(ramp)
    assert abs(ramp[0] - 1.0) < 1e-6
    assert abs(s.points[-1].value - 5.0) < 1e-6


def test_jitter_is_deterministic_and_window_independent():
    raw = {"name": "m", "baseline": 10.0, "jitter": 0.5}
    wide = expand_series(_spec(raw), WINDOW)
    narrow = expand_series(_spec(raw), (ANCHOR, ANCHOR + timedelta(minutes=5)))
    # a timestamp present in both windows must have an identical value
    wide_by_ts = {p.ts: p.value for p in wide.points}
    for p in narrow.points:
        assert wide_by_ts[p.ts] == p.value
    # and it isn't just baseline — jitter actually moved things
    assert any(p.value != 10.0 for p in narrow.points)


def test_percentiles_are_ordered():
    s = expand_series(
        _spec(
            {
                "name": "m",
                "baseline": 0.1,
                "segments": [{"at": "T+5m", "to": 3.0, "shape": "ramp", "over": "5m"}],
            }
        ),
        WINDOW,
    )
    assert s.summary.p50 <= s.summary.p95 <= s.summary.p99 <= s.summary.max


def test_ceil_and_floor_clamp():
    s = expand_series(
        _spec(
            {
                "name": "m",
                "baseline": 18.0,
                "jitter": 5.0,
                "ceil": 20.0,
                "floor": 16.0,
                "segments": [{"at": "T+1m", "to": 25.0, "shape": "step"}],
            }
        ),
        WINDOW,
    )
    assert s.summary.max == 20.0
    assert s.summary.min >= 16.0
