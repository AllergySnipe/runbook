"""Read-only investigation tools over the sim.

These are the "gather signal" step of the loop (`SPEC.md`). Right now they're
plain typed functions; the next slice wraps each in an Anthropic tool schema and
puts the model in a loop over them. Building them as ordinary functions first
means they get exhaustive `pytest` coverage and their return shapes get designed
carefully before a model ever sees them.

Design rules (they matter once the model is the caller):

* One job per tool. Structured returns, never prose. Every numeric answer the
  runbooks ask for ("p99 over 5m") is pre-computed in the return, so the model
  reads it instead of doing arithmetic.
* Unknown inputs and empty results return an explanatory object, never an
  exception and never a bare `[]` — the message teaches the caller what to try.
* Every tool is scoped to a time window (defaulting to the incident window) so
  the caller can narrow in.
* **All four are read-only.** State-changing actions (rollback, scale, failover)
  live in the runbooks but are gated behind human approval — Week 2. `TOOLS` is
  the allowlist that gate is built against (`SPEC.md` S2).
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from .sim import Scenario, load_scenario
from .sim.clock import TimeSpec
from .sim.infra import DependencyGraph, Deploy
from .sim.series import MetricSeries

# --- the allowlist (SPEC.md S2) -------------------------------------------

TOOLS: dict[str, Callable] = {}


def _tool(fn: Callable) -> Callable:
    TOOLS[fn.__name__] = fn
    return fn


def _scenario(ref: str | Scenario) -> Scenario:
    return ref if isinstance(ref, Scenario) else load_scenario(ref)


# --- query_metrics -------------------------------------------------------


@dataclass
class MetricQueryResult:
    metric: str
    window: tuple[datetime, datetime]
    series: list[MetricSeries]
    error: str | None = None
    available: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.series)


@_tool
def query_metrics(
    scenario: str | Scenario,
    metric: str,
    start: TimeSpec = None,
    end: TimeSpec = None,
) -> MetricQueryResult:
    """Time-series for `metric` over `[start, end]` (default: the incident window).

    Returns one `MetricSeries` per label-set (a latency metric typically has three:
    `quantile` p50/p95/p99), each carrying `points` and a pre-computed `summary`
    (`p50/p95/p99/min/max/mean/first/last/delta/trend`). Unknown metric → `error`
    plus `available` (exact names) and any substring matches in `series` is empty.
    """
    sc = _scenario(scenario)
    win = sc.window(start, end)
    exact = sc.metric_series(metric, win)
    if exact:
        return MetricQueryResult(metric=metric, window=win, series=exact)

    near = sc.metric_matches(metric)
    if len(near) == 1:
        return MetricQueryResult(metric=near[0], window=win, series=sc.metric_series(near[0], win))
    hint = f" did you mean: {', '.join(near)}?" if near else ""
    return MetricQueryResult(
        metric=metric,
        window=win,
        series=[],
        error=f"no metric named {metric!r}.{hint}",
        available=sc.metric_names(),
    )


# --- search_logs -------------------------------------------------------


@dataclass
class LogMatch:
    ts: datetime
    level: str
    service: str
    message: str
    line: str


@dataclass
class LogSearchResult:
    query: str
    window: tuple[datetime, datetime]
    matches: list[LogMatch]
    total_scanned: int
    truncated: bool = False
    hint: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.matches)


@_tool
def search_logs(
    scenario: str | Scenario,
    query: str,
    start: TimeSpec = None,
    end: TimeSpec = None,
    level: str | None = None,
    limit: int = 100,
) -> LogSearchResult:
    """Case-insensitive substring search over the log stream in `[start, end]`.

    `query` is matched against the rendered line; `level` (optional) filters to
    one severity. Returns up to `limit` `LogMatch`es oldest-first plus
    `total_scanned`. No matches → empty `matches` with a `hint` (and, if `query`
    itself found nothing anywhere in the window, a note that the absence may
    itself be signal — several runbooks expect *no* application errors).
    """
    sc = _scenario(scenario)
    win = sc.window(start, end)
    lines = sc.log_lines(win)
    if level:
        lines = [ln for ln in lines if ln.level.upper() == level.upper()]

    needle = query.lower()
    hits = [ln for ln in lines if needle in ln.render().lower()]
    truncated = len(hits) > limit
    matches = [
        LogMatch(
            ts=ln.ts,
            level=ln.level,
            service=ln.service,
            message=ln.message,
            line=ln.render(),
        )
        for ln in hits[:limit]
    ]
    hint = ""
    if not matches:
        hint = (
            f"nothing matched {query!r} in {len(lines)} lines "
            f"({win[0].isoformat()}..{win[1].isoformat()}). "
            "Absence of errors is itself a signal for some failure modes "
            "(CPU throttling, healthy dependencies)."
        )
    return LogSearchResult(
        query=query,
        window=win,
        matches=matches,
        total_scanned=len(lines),
        truncated=truncated,
        hint=hint,
    )


# --- get_recent_deploys ------------------------------------------------


@dataclass
class DeployListResult:
    window: tuple[datetime, datetime]
    deploys: list[Deploy]
    service: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.deploys)


@_tool
def get_recent_deploys(
    scenario: str | Scenario,
    service: str | None = None,
    start: TimeSpec = None,
    end: TimeSpec = None,
) -> DeployListResult:
    """Releases in `[start, end]` (default: incident window, widened to `T-2h` on
    the near side so a deploy just before onset is caught), oldest-first.

    Each `Deploy` has `version`, `at`, `migration` (bool), `migrations` (names),
    and `change`. `service` (optional) filters; default returns all services,
    since a neighbour's deploy can be the cause (consumer-lag, noisy-neighbour).
    """
    sc = _scenario(scenario)
    lo = sc.resolve(start) or sc.resolve("T-2h")
    hi = sc.resolve(end) or sc.incident_window[1]
    assert lo is not None and hi is not None
    deploys = sc.deploys((lo, hi))
    if service:
        deploys = [d for d in deploys if d.service == service]
    return DeployListResult(window=(lo, hi), deploys=deploys, service=service)


# --- get_service_dependencies ----------------------------------------


@_tool
def get_service_dependencies(
    scenario: str | Scenario,
    service: str | None = None,
) -> DependencyGraph:
    """The dependency graph for `service` (default: the scenario's own service):
    `upstreams` and `downstreams` (each with `kind`, `health`, optional
    `status_url`/`note`) and `neighbours`. Call `.unhealthy()` for the degraded
    or down edges.
    """
    sc = _scenario(scenario)
    graph = sc.dependencies()
    if service and service != graph.service:
        # v1 sim models one service's graph per scenario.
        return DependencyGraph(service=service)
    return graph


# --- the model-facing surface -------------------------------------------
#
# JSON Schemas the agent loop passes to the Anthropic API. The `scenario` a run
# is pinned to is *not* a parameter here — the executor binds it. Descriptions
# are what the model reads to decide when to reach for a tool, so they carry the
# "why", not just the "what".

_TIME_ARG = {
    "type": "string",
    "description": "ISO-8601, or an offset from incident start T+0 like 'T+5m' / 'T-1h30m'. "
    "Omit to use the full incident window.",
}

SCHEMAS: list[dict] = [
    {
        "name": "query_metrics",
        "description": (
            "Time-series for one metric over a window. Returns a series per label-set "
            "(latency metrics have quantile=p50/p95/p99) with a pre-computed summary "
            "(p50/p95/p99, min, max, mean, first, last, delta, trend). Unknown name → the "
            "list of available metrics. Call this to check the numbers a runbook's "
            "Diagnosis step names."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "exact metric name (Prometheus-style)"},
                "start": _TIME_ARG,
                "end": _TIME_ARG,
            },
            "required": ["metric"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_logs",
        "description": (
            "Case-insensitive substring search over the service's log stream in a window. "
            "Optional level filter (ERROR/WARN/INFO). Returns matching lines oldest-first "
            "plus how many were scanned. No matches returns a hint — and for some failure "
            "modes the absence of errors is itself the signal."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "substring to grep for"},
                "start": _TIME_ARG,
                "end": _TIME_ARG,
                "level": {"type": "string", "enum": ["ERROR", "WARN", "INFO"]},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_recent_deploys",
        "description": (
            "Releases in a window (default: incident window widened to T-2h), oldest-first, "
            "with version, timestamp, whether it carried a DB migration, and a change "
            "summary. Default covers all services — a neighbour's deploy can be the cause."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "filter to one service"},
                "start": _TIME_ARG,
                "end": _TIME_ARG,
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_service_dependencies",
        "description": (
            "The dependency graph for the service: upstreams and downstreams (each with "
            "kind, health, optional status_url/note) and neighbouring services. Use it to "
            "confirm or rule out an upstream/downstream as the cause."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"service": {"type": "string"}},
            "required": [],
            "additionalProperties": False,
        },
    },
]

_MAX_POINTS_IN_RESULT = 24  # downsample series before they go to the model


def _jsonable(obj: object) -> object:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def _downsample(points: list, n: int = _MAX_POINTS_IN_RESULT) -> list:
    if len(points) <= n:
        return points
    step = len(points) / n
    picked = [points[min(len(points) - 1, round(i * step))] for i in range(n)]
    if picked[-1] is not points[-1]:
        picked[-1] = points[-1]
    return picked


def _result_payload(name: str, result: object) -> object:
    """Trim a tool return to what the model needs, then make it JSON-safe."""
    if isinstance(result, MetricQueryResult):
        return {
            "metric": result.metric,
            "error": result.error,
            "available": result.available,
            "series": [
                {
                    "labels": s.labels,
                    "unit": s.unit,
                    "summary": _jsonable(s.summary),
                    "points": [[p.ts.isoformat(), p.value] for p in _downsample(s.points)],
                }
                for s in result.series
            ],
        }
    return _jsonable(result)


def run_tool(name: str, scenario: str | Scenario, tool_input: dict) -> tuple[str, bool]:
    """Execute an allowlisted tool. Returns `(json_string, is_error)`.

    `SPEC.md` S2: a name not in `TOOLS` is refused here, in code — never reachable
    even if the model asks for it.
    """
    fn = TOOLS.get(name)
    if fn is None:
        return json.dumps({"error": f"tool {name!r} is not on the allowlist"}), True
    try:
        result = fn(scenario, **tool_input)
    except TypeError as exc:  # bad arguments from the model
        return json.dumps({"error": f"bad arguments for {name}: {exc}"}), True
    except Exception as exc:  # noqa: BLE001 - surface any tool failure to the model, don't crash the loop
        return json.dumps({"error": f"{name} failed: {exc}"}), True
    return json.dumps(_result_payload(name, result), default=str), False
