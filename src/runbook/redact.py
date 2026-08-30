"""Deterministic secret / PII scrubbing (SPEC S5).

Every string that leaves this process for a model provider or a persisted trace
passes through `redact()` first. Two enforcement points (ADR-0011):

- `llm.py` — the choke point: `system` + every message `content`, on every
  provider call. The structural guarantee that nothing reaches a provider raw.
- `core/loop.py` — targeted: each tool result before it enters the message
  history *and* the audit record, plus the runbook text before the grounding
  check (so S3 verifies against exactly what the model saw).

Deterministic on purpose — regex + checksums, no model pass. Auditable, free,
offline, `pytest`-able. It catches *structured* secrets (keys, tokens,
connection strings, cards, emails, private IPs), not free-form PII like names;
that tradeoff is recorded in ADR-0011.

`redact()` is idempotent: the `[redacted:*]` placeholders match no detector, so
`redact(redact(x)).text == redact(x).text`.

Lives at the package top level (not `core/`) so `llm.py` can import it without a
cycle — `core/__init__` pulls in the loop, which imports `llm`.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RedactionSpan:
    """Where a placeholder sits in the *redacted* text, and what kind it replaced."""

    start: int
    end: int
    kind: str


@dataclass
class RedactionResult:
    text: str
    spans: list[RedactionSpan] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.spans)

    @property
    def by_kind(self) -> dict[str, int]:
        return dict(Counter(s.kind for s in self.spans))


# --- validators (a regex match is necessary, not sufficient) ------------------


def _luhn(candidate: str) -> bool:
    """The checksum every real payment card satisfies. Without it, `\\d{13,19}`
    also eats trace ids, byte counts and timestamps — a random number passes
    ~10% of the time, a real card 100%."""
    digits = [int(c) for c in candidate if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _is_private_ipv4(candidate: str) -> bool:
    """Only RFC 1918 / loopback / link-local. Public IPs are, by definition,
    public — and the danluu postmortems are full of `1.1.1.1`. The sensitive
    thing about an IP is internal network topology, which is exactly the private
    ranges."""
    parts = candidate.split(".")
    if len(parts) != 4:
        return False
    try:
        a, b, _c, _d = (int(p) for p in parts)
    except ValueError:
        return False
    if not all(0 <= int(p) <= 255 for p in parts):
        return False
    return (
        a == 10
        or (a == 172 and 16 <= b <= 31)
        or (a == 192 and b == 168)
        or a == 127
        or (a == 169 and b == 254)
    )


# --- detectors ---------------------------------------------------------------
# (kind, pattern, capture-group, validator). Group 1 for keyword-anchored
# patterns where only the value is the secret; group 0 otherwise. Order is
# irrelevant — overlaps are resolved by position in `redact()`.

_Detector = tuple[str, re.Pattern[str], int, Callable[[str], bool] | None]

_DETECTORS: list[_Detector] = [
    (
        "private-key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        0,
        None,
    ),
    # scheme://user:password@host — the `user:pass@` authority is the secret.
    # `[]` excluded from the userinfo so a `[redacted:*]` placeholder can't be
    # re-matched on a second pass (idempotency).
    (
        "connection-string",
        re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@\[\]]+:[^\s:/@\[\]]+@[^\s/\"'\]]+"),
        0,
        None,
    ),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), 0, None),
    # vendor-assigned key prefixes — near-zero false positives
    ("api-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), 0, None),
    ("api-key", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), 0, None),
    ("api-key", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), 0, None),
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"), 0, None),
    ("api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), 0, None),
    ("api-key", re.compile(r"\b[sr]k_(?:live|test)_[0-9A-Za-z]{16,}\b"), 0, None),
    # `Authorization: Bearer|Basic|Token <blob>` and a bare `Bearer <blob>`
    (
        "bearer-token",
        re.compile(
            r"(?i)\bAuthorization\s*:\s*(?:Bearer|Basic|Token)\s+([A-Za-z0-9._+/=][A-Za-z0-9._\-+/=]{7,})"
        ),
        1,
        None,
    ),
    (
        "bearer-token",
        re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._+/=][A-Za-z0-9._\-+/=]{9,})"),
        1,
        None,
    ),
    # `<name>=<value>` / `<name>: <value>` where the name ends in a secret-ish
    # word. The optional identifier prefix catches `db_password=`, `csrf_token=`;
    # the `[:=]` separator keeps runbook prose ("password rotation", "the token
    # bucket") from ever matching.
    (
        "credential",
        re.compile(
            r"(?i)(?<![A-Za-z0-9_])[A-Za-z0-9_.\-]{0,32}"
            r"(?:api[_-]?key|x-api-key|access[_-]?token|auth[_-]?token|client[_-]?secret"
            r"|password|passwd|pwd|secret|token)"
            r"\s*[:=]\s*[\"']?([^\s\"',;)\[\]]{6,})"
        ),
        1,
        None,
    ),
    ("card", re.compile(r"\b\d(?:[ -]?\d){12,18}\b"), 0, _luhn),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), 0, None),
    ("private-ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), 0, _is_private_ipv4),
]

_PLACEHOLDER = "[redacted:{kind}]"


def redact(text: str) -> RedactionResult:
    """Scrub every detected secret / PII span, replacing it with
    `[redacted:<kind>]`. Returns the clean text plus a span per replacement
    (indices into the *returned* text)."""
    if not text:
        return RedactionResult(text=text)

    candidates: list[tuple[int, int, int, str]] = []
    for priority, (kind, pattern, group, validator) in enumerate(_DETECTORS):
        for m in pattern.finditer(text):
            start, end = m.span(group)
            if start == end:
                continue
            if validator is not None and not validator(m.group(group)):
                continue
            candidates.append((start, end, priority, kind))

    if not candidates:
        return RedactionResult(text=text)

    # resolve overlaps: earliest start wins; then the more specific detector
    # (lower `_DETECTORS` index — e.g. a vendor key prefix beats the generic
    # email pattern on `ghp_…@github.com`); then the longer span
    candidates.sort(key=lambda c: (c[0], c[2], -(c[1] - c[0])))
    kept: list[tuple[int, int, str]] = []
    last_end = -1
    for start, end, _priority, kind in candidates:
        if start < last_end:
            continue
        kept.append((start, end, kind))
        last_end = end

    out: list[str] = []
    spans: list[RedactionSpan] = []
    written = 0
    cursor = 0
    for start, end, kind in kept:
        prefix = text[cursor:start]
        out.append(prefix)
        written += len(prefix)
        token = _PLACEHOLDER.format(kind=kind)
        spans.append(RedactionSpan(written, written + len(token), kind))
        out.append(token)
        written += len(token)
        cursor = end
    out.append(text[cursor:])
    return RedactionResult(text="".join(out), spans=spans)
