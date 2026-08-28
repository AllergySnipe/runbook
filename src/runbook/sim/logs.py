"""Log lines: the `LogLine` record + loading a scenario's hand-written signal log.

A scenario's `logs.jsonl` holds the lines a runbook's Diagnosis step greps for —
the *signal*. Each JSON object: `{"at": "T+3m", "level": "ERROR", "message": "…"}`
(optional `count` to repeat a recurring line, optional `fields` dict). The sim
merges these with generated noise (`noise.py`) into one time-ordered stream.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .clock import parse_time


@dataclass(frozen=True)
class LogLine:
    ts: datetime
    level: str
    service: str
    message: str
    source: str  # "signal" | "noise"
    fields: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        base = f"{self.ts.isoformat()} {self.level:<5} {self.service} {self.message}"
        if self.fields:
            extra = " ".join(f"{k}={v}" for k, v in self.fields.items())
            return f"{base} {extra}"
        return base


def load_signal_logs(path: Path, anchor: datetime, service: str) -> list[LogLine]:
    """Parse `logs.jsonl`. Missing file → no signal lines (a `healthy` scenario)."""
    if not path.exists():
        return []
    out: list[LogLine] = []
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{lineno}: invalid JSON ({exc})") from exc
        at = parse_time(obj["at"], anchor)
        if at is None:
            raise ValueError(f"{path.name}:{lineno}: log line needs an 'at' time")
        count = int(obj.get("count", 1))
        spacing = timedelta(seconds=float(obj.get("every_s", 20)))
        for i in range(count):
            out.append(
                LogLine(
                    ts=at + spacing * i,
                    level=obj.get("level", "INFO"),
                    service=obj.get("service", service),
                    message=obj["message"],
                    source="signal",
                    fields={str(k): str(v) for k, v in (obj.get("fields") or {}).items()},
                )
            )
    out.sort(key=lambda ln: ln.ts)
    return out
