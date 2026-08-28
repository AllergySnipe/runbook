"""Expand a compact metric spec into a deterministic time-series.

Authoring 300 data points by hand is untenable, so a fixture describes a series by
its *shape* and the sim expands it at query time:

    name: paymentsvc_db_pool_checked_out
    unit: connections
    baseline: 6
    segments:
      - {at: "T+1m", to: 20, shape: ramp, over: "3m"}   # climbs to the pool size
      - {at: "T+27m", to: 6, shape: step}               # recovers after the fix

The value starts at `baseline`, holds flat, and each segment moves it toward a new
level — `step` (jump) or `ramp` (linear over `over`). Optional `pattern: sawtooth`
adds a bursty oscillation (the CFS-throttling failure mode). `jitter` adds small
deterministic pseudo-noise so a series doesn't look synthetic-perfect.

Determinism: jitter is seeded from `(series key, timestamp)`, so a point's value
is identical no matter what window a tool asks for. No `random` global, no clock.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .clock import parse_duration, parse_time

DEFAULT_STEP = timedelta(seconds=30)


@dataclass(frozen=True)
class MetricPoint:
    ts: datetime
    value: float


@dataclass(frozen=True)
class MetricSummary:
    count: int
    first: float
    last: float
    delta: float  # last - first
    min: float
    max: float
    mean: float
    p50: float
    p95: float
    p99: float
    trend: str  # "rising" | "falling" | "flat"


@dataclass(frozen=True)
class MetricSeries:
    name: str
    unit: str
    labels: dict[str, str]
    points: list[MetricPoint]
    summary: MetricSummary

    @property
    def selector(self) -> str:
        if not self.labels:
            return self.name
        inner = ",".join(f'{k}="{v}"' for k, v in sorted(self.labels.items()))
        return f"{self.name}{{{inner}}}"


@dataclass
class _Segment:
    at: datetime
    to: float
    shape: str  # "step" | "ramp"
    over: timedelta

    @property
    def end(self) -> datetime:
        return self.at if self.shape == "step" else self.at + self.over


@dataclass
class SeriesSpec:
    name: str
    baseline: float
    unit: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    jitter: float = 0.0
    pattern: str = "flat"  # "flat" | "sawtooth"
    sawtooth_period: timedelta = timedelta(minutes=2)
    sawtooth_amplitude: float = 0.0
    floor: float | None = None
    ceil: float | None = None
    segments: list[_Segment] = field(default_factory=list)

    @property
    def selector_key(self) -> str:
        """Stable string identity for hashing (the `labels` dict isn't hashable)."""
        inner = ",".join(f"{k}={v}" for k, v in sorted(self.labels.items()))
        return f"{self.name}|{inner}"

    @classmethod
    def from_dict(cls, raw: dict, anchor: datetime) -> SeriesSpec:
        segs = []
        for s in raw.get("segments", []):
            at = parse_time(s["at"], anchor)
            if at is None:
                raise ValueError(f"segment for {raw['name']!r} needs an 'at' time")
            segs.append(
                _Segment(
                    at=at,
                    to=float(s["to"]),
                    shape=s.get("shape", "step"),
                    over=parse_duration(s.get("over", 0)),
                )
            )
        segs.sort(key=lambda seg: seg.at)
        saw = raw.get("sawtooth", {})
        return cls(
            name=raw["name"],
            baseline=float(raw["baseline"]),
            unit=raw.get("unit", ""),
            labels={str(k): str(v) for k, v in (raw.get("labels") or {}).items()},
            jitter=float(raw.get("jitter", 0.0)),
            pattern=raw.get("pattern", "flat"),
            sawtooth_period=parse_duration(saw.get("period", "2m")),
            sawtooth_amplitude=float(saw.get("amplitude", 0.0)),
            floor=None if raw.get("floor") is None else float(raw["floor"]),
            ceil=None if raw.get("ceil") is None else float(raw["ceil"]),
            segments=segs,
        )


def _trajectory(spec: SeriesSpec, ts: datetime) -> float:
    """The piecewise base value at `ts`, before pattern + jitter."""
    value = spec.baseline
    for seg in spec.segments:
        if ts < seg.at:
            break
        if seg.shape == "step" or ts >= seg.end:
            value = seg.to
        else:  # mid-ramp
            frac = (ts - seg.at) / (seg.end - seg.at)
            value = value + (seg.to - value) * frac
            break
    return value


def _jitter(spec: SeriesSpec, ts: datetime) -> float:
    if spec.jitter == 0.0:
        return 0.0
    key = f"{spec.selector_key}|{int(ts.timestamp())}".encode()
    digest = hashlib.sha256(key).digest()
    unit = int.from_bytes(digest[:8], "big") / 2**64  # [0, 1)
    return spec.jitter * (2.0 * unit - 1.0)


def _sawtooth(spec: SeriesSpec, ts: datetime) -> float:
    if spec.pattern != "sawtooth" or spec.sawtooth_amplitude == 0.0:
        return 0.0
    period = spec.sawtooth_period.total_seconds()
    phase = (ts.timestamp() % period) / period  # [0, 1)
    # rising ramp then sharp drop, centred on zero
    return spec.sawtooth_amplitude * (2.0 * phase - 1.0)


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, math.ceil(q * len(sorted_vals)) - 1))
    return sorted_vals[idx]


def _summarise(points: list[MetricPoint]) -> MetricSummary:
    vals = [p.value for p in points]
    sv = sorted(vals)
    first, last = vals[0], vals[-1]
    third = max(1, len(vals) // 3)
    head = sum(vals[:third]) / third
    tail = sum(vals[-third:]) / third
    denom = abs(head) + 1e-9
    if (tail - head) / denom > 0.15:
        trend = "rising"
    elif (head - tail) / denom > 0.15:
        trend = "falling"
    else:
        trend = "flat"
    return MetricSummary(
        count=len(vals),
        first=round(first, 6),
        last=round(last, 6),
        delta=round(last - first, 6),
        min=round(sv[0], 6),
        max=round(sv[-1], 6),
        mean=round(sum(vals) / len(vals), 6),
        p50=round(_percentile(sv, 0.50), 6),
        p95=round(_percentile(sv, 0.95), 6),
        p99=round(_percentile(sv, 0.99), 6),
        trend=trend,
    )


def expand_series(
    spec: SeriesSpec,
    window: tuple[datetime, datetime],
    step: timedelta = DEFAULT_STEP,
) -> MetricSeries:
    lo, hi = window
    points: list[MetricPoint] = []
    ts = lo
    while ts <= hi:
        value = _trajectory(spec, ts) + _sawtooth(spec, ts) + _jitter(spec, ts)
        if spec.floor is not None:
            value = max(spec.floor, value)
        elif spec.baseline >= 0:
            value = max(0.0, value)
        if spec.ceil is not None:
            value = min(spec.ceil, value)
        points.append(MetricPoint(ts=ts, value=round(value, 6)))
        ts += step
    return MetricSeries(
        name=spec.name,
        unit=spec.unit,
        labels=dict(spec.labels),
        points=points,
        summary=_summarise(points),
    )
