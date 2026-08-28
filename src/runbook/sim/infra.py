"""Deploy history + service-dependency graph records, and their fixture loaders.

`deploys.yaml` — a list of releases, newest last:

    - {at: "T-6m", service: paymentsvc, version: "2026.8.28-a1b2c3d",
       migration: true, migrations: ["0042_add_charge_region"],
       change: "add charges.region column + backfill"}

`dependencies.yaml` — one graph for the scenario's service:

    service: paymentsvc
    upstreams:
      - {name: postgres-primary, kind: database, health: degraded,
         note: "connection wait times elevated"}
      - {name: acquirer-gw, kind: external_api, health: healthy,
         status_url: "https://status.acquirer-gw.example"}
    downstreams:
      - {name: ledger, kind: service, health: healthy}
    neighbours: [checkout-web, fraud-scoring]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from .clock import parse_time


@dataclass(frozen=True)
class Deploy:
    at: datetime
    service: str
    version: str
    migration: bool
    migrations: list[str]
    change: str


@dataclass(frozen=True)
class Dependency:
    name: str
    kind: str  # database | cache | queue | external_api | service
    health: str  # healthy | degraded | down | unknown
    note: str = ""
    status_url: str | None = None


@dataclass(frozen=True)
class DependencyGraph:
    service: str
    upstreams: list[Dependency] = field(default_factory=list)
    downstreams: list[Dependency] = field(default_factory=list)
    neighbours: list[str] = field(default_factory=list)

    def unhealthy(self) -> list[Dependency]:
        bad = {"degraded", "down"}
        return [d for d in (*self.upstreams, *self.downstreams) if d.health in bad]


def load_deploys(path: Path, anchor: datetime, service: str) -> list[Deploy]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or []
    out: list[Deploy] = []
    for d in raw:
        at = parse_time(d["at"], anchor)
        if at is None:
            raise ValueError(f"{path.name}: deploy entry needs an 'at' time")
        out.append(
            Deploy(
                at=at,
                service=d.get("service", service),
                version=str(d["version"]),
                migration=bool(d.get("migration", False)),
                migrations=[str(m) for m in (d.get("migrations") or [])],
                change=d.get("change", ""),
            )
        )
    out.sort(key=lambda x: x.at)
    return out


def _dep(raw: dict) -> Dependency:
    return Dependency(
        name=raw["name"],
        kind=raw.get("kind", "service"),
        health=raw.get("health", "unknown"),
        note=raw.get("note", ""),
        status_url=raw.get("status_url"),
    )


def load_dependencies(path: Path, service: str) -> DependencyGraph:
    if not path.exists():
        return DependencyGraph(service=service)
    raw = yaml.safe_load(path.read_text()) or {}
    return DependencyGraph(
        service=raw.get("service", service),
        upstreams=[_dep(d) for d in raw.get("upstreams", [])],
        downstreams=[_dep(d) for d in raw.get("downstreams", [])],
        neighbours=[str(n) for n in raw.get("neighbours", [])],
    )
