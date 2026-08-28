"""Synthetic incident clock.

Every scenario has an **anchor** — a UTC datetime that is `T+0`, the moment the
incident starts. Fixtures and tool arguments express times either as an absolute
ISO-8601 string (`2026-08-28T14:07:00Z`) or relative to the anchor (`T+7m`,
`T-10m`, `T+1h30m`, `T+0`). Nothing in the sim ever calls `datetime.now()` — a
scenario's world is frozen, so tests are deterministic.

`parse_time` turns any of those forms (or a `datetime`) into an aware UTC
`datetime`. `parse_window` resolves a `(start, end)` pair, falling back to a
supplied default when either side is `None`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

TimeSpec = str | datetime | None

_REL_RE = re.compile(r"^T([+-])(0|(?:\d+[smhd])+)$")
_PART_RE = re.compile(r"(\d+)([smhd])")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _to_utc(dt: datetime) -> datetime:
    """Coerce to an aware UTC datetime (assume naive datetimes are already UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_offset(text: str) -> timedelta:
    """`T+1h30m` / `T-10m` / `T+0` → a `timedelta` relative to the anchor."""
    m = _REL_RE.match(text.strip())
    if not m:
        raise ValueError(f"bad relative time {text!r}: expected e.g. 'T+0', 'T+7m', 'T-1h30m'")
    sign = 1 if m.group(1) == "+" else -1
    body = m.group(2)
    if body == "0":
        return timedelta(0)
    seconds = sum(int(n) * _UNIT_SECONDS[u] for n, u in _PART_RE.findall(body))
    return timedelta(seconds=sign * seconds)


def parse_duration(text: str | float) -> timedelta:
    """`"5m"` / `"90s"` / `"1h30m"` / a number of seconds → a `timedelta`."""
    if isinstance(text, (int, float)):
        return timedelta(seconds=float(text))
    parts = _PART_RE.findall(text.strip())
    if not parts:
        raise ValueError(f"bad duration {text!r}: expected e.g. '5m', '90s', '1h30m'")
    return timedelta(seconds=sum(int(n) * _UNIT_SECONDS[u] for n, u in parts))


def parse_time(value: TimeSpec, anchor: datetime) -> datetime | None:
    """Resolve a time spec against `anchor`. `None` passes through as `None`."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _to_utc(value)
    text = value.strip()
    if text.startswith(("T+", "T-")):
        return _to_utc(anchor) + parse_offset(text)
    try:
        return _to_utc(datetime.fromisoformat(text))  # Py 3.11+ parses a trailing 'Z'
    except ValueError as exc:
        raise ValueError(f"bad time {value!r}: expected ISO-8601 or a 'T±…' offset") from exc


def parse_window(
    start: TimeSpec,
    end: TimeSpec,
    anchor: datetime,
    default: tuple[datetime, datetime],
) -> tuple[datetime, datetime]:
    """Resolve `(start, end)`, substituting `default` for a `None` side.

    Raises if the resolved window is empty or inverted — a misuse worth surfacing
    loudly rather than returning zero rows.
    """
    lo = parse_time(start, anchor) or default[0]
    hi = parse_time(end, anchor) or default[1]
    if hi <= lo:
        raise ValueError(f"empty time window: start {lo.isoformat()} >= end {hi.isoformat()}")
    return lo, hi
