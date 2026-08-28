"""Load a scenario and answer questions about its frozen world.

A scenario is a directory under `sim/scenarios/<name>/`:

    scenario.yaml      manifest: service, anchor (T+0), incident window, the alert
                       that fires, the runbook this world is built to match
    metrics.yaml       list of compact series specs (see series.py)
    logs.jsonl         hand-written signal log lines (see logs.py); optional
    deploys.yaml       release history (see infra.py); optional
    dependencies.yaml  service-dependency graph (see infra.py); optional

`Scenario` is what the tool layer talks to. It never touches Postgres or the
clock — everything is derived from these files.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from .clock import TimeSpec, parse_time, parse_window
from .infra import DependencyGraph, Deploy, load_dependencies, load_deploys
from .logs import LogLine, load_signal_logs
from .noise import generate_noise
from .series import DEFAULT_STEP, MetricSeries, SeriesSpec, expand_series

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
_ANCHOR_ORIGIN = datetime(
    1970, 1, 1, tzinfo=UTC
)  # unused placeholder; manifest anchors are absolute


def list_scenarios() -> list[str]:
    if not SCENARIOS_DIR.is_dir():
        return []
    return sorted(p.name for p in SCENARIOS_DIR.iterdir() if (p / "scenario.yaml").is_file())


@dataclass
class Scenario:
    name: str
    service: str
    title: str
    severity: str
    alert: str
    summary: str
    anchor: datetime
    incident_window: tuple[datetime, datetime]
    expected_runbook: str | None
    _specs: list[SeriesSpec]
    _signal_logs: list[LogLine]
    _deploys: list[Deploy]
    _dependencies: DependencyGraph
    _noise_seed: int
    _noise_rate: float

    # -- time helpers -------------------------------------------------------

    def resolve(self, value: TimeSpec) -> datetime | None:
        return parse_time(value, self.anchor)

    def window(self, start: TimeSpec = None, end: TimeSpec = None) -> tuple[datetime, datetime]:
        """Resolve a `(start, end)` pair, defaulting to the incident window."""
        return parse_window(start, end, self.anchor, self.incident_window)

    # -- metrics ----------------------------------------------------------

    def metric_names(self) -> list[str]:
        return sorted({s.name for s in self._specs})

    def metric_series(
        self,
        metric: str,
        window: tuple[datetime, datetime] | None = None,
        step: timedelta = DEFAULT_STEP,
    ) -> list[MetricSeries]:
        """Every series whose name equals `metric` (there may be several, one per
        label-set — e.g. a latency metric with `quantile` p50/p95/p99)."""
        win = window or self.incident_window
        return [expand_series(s, win, step) for s in self._specs if s.name == metric]

    def metric_matches(self, fragment: str) -> list[str]:
        frag = fragment.lower()
        return [n for n in self.metric_names() if frag in n.lower()]

    # -- logs -----------------------------------------------------------

    def log_lines(self, window: tuple[datetime, datetime] | None = None) -> list[LogLine]:
        lo, hi = window or self.incident_window
        noise = generate_noise(
            seed=self._noise_seed,
            lines_per_min=self._noise_rate,
            window=(lo, hi),
            service=self.service,
        )
        merged = [ln for ln in (*self._signal_logs, *noise) if lo <= ln.ts <= hi]
        merged.sort(key=lambda ln: ln.ts)
        return merged

    # -- deploys / dependencies ---------------------------------------

    def deploys(self, window: tuple[datetime, datetime] | None = None) -> list[Deploy]:
        if window is None:
            return list(self._deploys)
        lo, hi = window
        return [d for d in self._deploys if lo <= d.at <= hi]

    def dependencies(self) -> DependencyGraph:
        return self._dependencies


def load_scenario(name: str) -> Scenario:
    root = SCENARIOS_DIR / name
    manifest_path = root / "scenario.yaml"
    if not manifest_path.is_file():
        known = ", ".join(list_scenarios()) or "(none)"
        raise FileNotFoundError(f"unknown scenario {name!r}. known: {known}")

    m = yaml.safe_load(manifest_path.read_text()) or {}
    service = m.get("service", "paymentsvc")
    # The manifest's `anchor` is always an absolute ISO timestamp, so the second
    # arg (the relative-time origin) is never consulted here.
    anchor = parse_time(str(m["anchor"]), _ANCHOR_ORIGIN)
    assert anchor is not None

    win_raw = m.get("incident_window", ["T-10m", "T+30m"])
    lo = parse_time(win_raw[0], anchor)
    hi = parse_time(win_raw[1], anchor)
    assert lo is not None and hi is not None

    metrics_raw = (
        yaml.safe_load((root / "metrics.yaml").read_text())
        if (root / "metrics.yaml").is_file()
        else []
    )
    specs = [SeriesSpec.from_dict(r, anchor) for r in (metrics_raw or [])]

    noise = m.get("noise", {})
    return Scenario(
        name=name,
        service=service,
        title=m.get("title", name),
        severity=m.get("severity", ""),
        alert=m.get("alert", ""),
        summary=m.get("summary", ""),
        anchor=anchor,
        incident_window=(lo, hi),
        expected_runbook=m.get("expected_runbook"),
        _specs=specs,
        _signal_logs=load_signal_logs(root / "logs.jsonl", anchor, service),
        _deploys=load_deploys(root / "deploys.yaml", anchor, service),
        _dependencies=load_dependencies(root / "dependencies.yaml", service),
        _noise_seed=int(noise.get("seed", 0)),
        _noise_rate=float(noise.get("lines_per_min", 0.0)),
    )
