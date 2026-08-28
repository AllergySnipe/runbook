"""Deterministic background-log generator — the replacement for a real log dataset.

`search_logs` is only an honest test if the signal lines a runbook names
(`pool timeout: no connection available after 5000ms`) are buried in a stream of
plausible, unrelated lines. Public log datasets (Loghub, LO2, …) are either the
wrong domain (supercomputers, Hadoop) or huge research bundles, and none of them
emit *payments* lines. So the sim synthesises its own chaff: payments-domain
INFO/WARN lines at a configurable rate, seeded per scenario so the stream is
byte-identical every run. See ADR-0004; OpenTelemetry Demo is the dataset to
revisit if we ever want real captured logs.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from .logs import LogLine

# (level, template) — `{}` fields are filled from the seeded RNG via _FIELDS
_TEMPLATES: list[tuple[str, str]] = [
    ("INFO", "GET /healthz 200 {lat_ms}ms"),
    ("INFO", "GET /readyz 200 {lat_ms}ms"),
    ("INFO", "POST /charges 200 merchant={merchant} amount={amount} {lat_ms}ms"),
    ("INFO", "POST /charges 200 merchant={merchant} amount={amount} {lat_ms}ms"),
    ("INFO", "POST /refunds 200 merchant={merchant} amount={amount} {lat_ms}ms"),
    ("INFO", "charge accepted id=ch_{hex} merchant={merchant} amount={amount}"),
    ("INFO", "idempotency hit key={hex} merchant={merchant}"),
    ("INFO", "published payments.charge.succeeded partition={part} offset={offset}"),
    ("INFO", "acquirer-gw request ok route=primary {lat_ms}ms"),
    ("INFO", "db pool acquire ok checked_out={co}/{pool} wait={wait_ms}ms"),
    ("INFO", "redis GET idempotency:{hex} -> hit"),
    ("INFO", "config reload ok version={cfgver}"),
    ("INFO", "GET /metrics 200 {lat_ms}ms"),
    ("WARN", "slow request POST /charges {lat_ms}ms merchant={merchant}"),
    ("WARN", "webhook delivery retry attempt={attempt} merchant={merchant}"),
    ("WARN", "acquirer-gw latency elevated route=primary {lat_ms}ms"),
]


def _fields(rng: random.Random) -> dict[str, object]:
    return {
        "lat_ms": rng.randint(8, 140),
        "wait_ms": rng.randint(0, 25),
        "merchant": f"m_{rng.randint(1000, 9999)}",
        "amount": rng.randint(199, 48000),
        "hex": f"{rng.randrange(16**12):012x}",
        "part": rng.randint(0, 7),
        "offset": rng.randint(10_000_000, 99_999_999),
        "co": rng.randint(2, 12),
        "pool": 20,
        "cfgver": rng.randint(40, 71),
        "attempt": rng.randint(1, 3),
    }


def generate_noise(
    *,
    seed: int,
    lines_per_min: float,
    window: tuple[datetime, datetime],
    service: str,
) -> list[LogLine]:
    """Chaff lines spread across `window` at roughly `lines_per_min`."""
    if lines_per_min <= 0:
        return []
    lo, hi = window
    span_min = (hi - lo).total_seconds() / 60.0
    n = max(0, round(span_min * lines_per_min))
    rng = random.Random(seed)
    out: list[LogLine] = []
    for _ in range(n):
        offset = rng.random() * (hi - lo).total_seconds()
        ts = lo + timedelta(seconds=offset)
        level, template = rng.choice(_TEMPLATES)
        out.append(
            LogLine(
                ts=ts,
                level=level,
                service=service,
                message=template.format(**_fields(rng)),
                source="noise",
            )
        )
    out.sort(key=lambda ln: ln.ts)
    return out
