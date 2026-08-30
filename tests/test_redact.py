"""The deterministic S5 scrubber (`runbook.redact`, ADR-0011).

Two acceptance bars:
  1. every structured secret / PII kind is caught in a realistic log line;
  2. real runbook prose and benign log noise pass through **byte-for-byte** —
     an over-redaction that corrupts the runbook would break grounding (S3).
Plus idempotency, since `llm.py` re-scrubs what `core/loop.py` already scrubbed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runbook.redact import redact

_CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "synthetic" / "paymentsvc"


# --- positive: each kind is caught ------------------------------------------

POSITIVE = [
    ("email", "alert ack'd by oncall-lead@paymentsvc.example.com at 03:12", "email"),
    (
        "connection-string",
        "could not connect to postgresql://pmt_app:s3cr3t-pw@db-primary.internal:5432/paymentsvc",
        "connection-string",
    ),
    (
        "bearer-token",
        'upstream 401: sent header "Authorization: Bearer eyJ0okenlooking.value-1234567890"',
        "bearer-token",
    ),
    ("api-key aws", "boto3 using AKIA1234567890ABCDEF from env", "api-key"),
    (
        "api-key openai",
        "openrouter call failed with key sk-or-v1-abcdef0123456789abcdef0123456789",
        "api-key",
    ),
    ("api-key github", "git clone https://ghp_" + "a" * 36 + "@github.com/x/y", "api-key"),
    (
        "api-key slack",
        "slack webhook rejected token xoxb-2468013579-abcdefghijkl",
        "api-key",
    ),
    (
        "jwt",
        "session cookie = eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.dozjgNryP4J3jVmNHl0w5N_XgL0n3I",
        "jwt",
    ),
    (
        "credential kv",
        "config dump: db_password=hunter2-not-great redis_secret=aVeryLongSecretValue",
        "credential",
    ),
    ("card", "declined charge on card 4111 1111 1111 1111 (test PAN)", "card"),
    ("private-ip 10", "connection reset by peer 10.4.12.9:8443", "private-ip"),
    ("private-ip 192", "pod cidr 192.168.24.7 unreachable", "private-ip"),
    ("private-ip 172", "gateway 172.20.0.1 timed out", "private-ip"),
]


@pytest.mark.parametrize("label,text,kind", POSITIVE, ids=[p[0] for p in POSITIVE])
def test_secret_is_redacted(label, text, kind):
    r = redact(text)
    assert r.count >= 1, f"{label}: nothing redacted"
    assert kind in r.by_kind, f"{label}: expected a {kind} span, got {r.by_kind}"
    assert f"[redacted:{kind}]" in r.text
    # the raw secret value is gone
    secret_bits = {
        "email": ["oncall-lead@paymentsvc.example.com"],
        "connection-string": ["s3cr3t-pw", "pmt_app"],
        "bearer-token": ["eyJ0okenlooking.value-1234567890"],
        "api-key": ["AKIA1234567890ABCDEF", "sk-or-v1-", "ghp_", "xoxb-2468013579"],
        "jwt": ["eyJhbGciOiJIUzI1NiJ9"],
        "credential": ["hunter2-not-great", "aVeryLongSecretValue"],
        "card": ["4111 1111 1111 1111", "4111111111111111"],
        "private-ip": ["10.4.12.9", "192.168.24.7", "172.20.0.1"],
    }
    for bit in secret_bits[kind]:
        if bit in text:
            assert bit not in r.text, f"{label}: {bit!r} survived"


# --- negative: real runbook prose is untouched -----------------------------

RUNBOOK_LINES = [
    "**[state-changing — needs approval] Raise Redis `maxmemory` / scale the instance**",
    "switch `maxmemory-policy` to `noeviction` for the idempotency keyspace.",
    "`query_metrics` — Redis `used_memory` / `maxmemory`, `evicted_keys` rate, `keyspace_hits`",
    "**[read-only] Confirm scope** — is it one pod or all? One pod suggests a leak; restart it.",
    "3. TTL on idempotency keys set too short relative to client retry windows.",
    "a retried `POST /charges` with the same `Idempotency-Key` returns the original result",
    "CPU limits set too close to (or below) real burst demand — throttling under normal load.",
]

BENIGN_NOISE = [
    "deploy paymentsvc v2.14.3 completed in 47s",
    "request id 7f3c9a1e-4b2d-11ef-9c8a-0242ac120002 took 1234ms",
    "cloudflare 1.1.1.1 and google 8.8.8.8 both resolved fine",
    "order 1234567890123456 failed luhn — not a real card",  # 16 digits, fails Luhn
    "public gateway 172.32.0.1 is fine (outside RFC1918)",
    "retry budget 100000000000000 exhausted",
    "the token bucket refills at 50/s; rotate the password on schedule",
]


@pytest.mark.parametrize("line", RUNBOOK_LINES + BENIGN_NOISE)
def test_prose_passes_through_unchanged(line):
    r = redact(line)
    assert r.text == line, f"over-redacted: {r.by_kind}"
    assert r.count == 0


def test_every_synthetic_runbook_is_untouched():
    """The whole acceptance bar for over-redaction: run the scrubber over every
    committed runbook and assert not one byte changes."""
    files = sorted(_CORPUS.glob("*.md"))
    assert files, "no synthetic runbooks found"
    for f in files:
        original = f.read_text()
        assert redact(original).text == original, f"{f.name} was modified by redact()"


# --- idempotency ----------------------------------------------------------


@pytest.mark.parametrize("text", [p[1] for p in POSITIVE])
def test_redaction_is_idempotent(text):
    once = redact(text).text
    twice = redact(once).text
    assert twice == once


def test_placeholder_matches_no_detector():
    placeholders = " ".join(
        f"[redacted:{k}]"
        for k in [
            "email",
            "connection-string",
            "bearer-token",
            "api-key",
            "jwt",
            "credential",
            "card",
            "private-ip",
            "private-key",
        ]
    )
    assert redact(placeholders).count == 0


# --- validators ---------------------------------------------------------------


def test_luhn_gate_on_long_numbers():
    assert redact("card 4111111111111111 here").count == 1  # valid Luhn
    assert redact("id 1234567890123456 here").count == 0  # fails Luhn
    assert redact("ts 20240101120000123456 ns").count == 0  # 20 digits, too long


def test_rfc1918_only():
    assert redact("10.0.0.1").count == 1
    assert redact("172.16.5.5").count == 1
    assert redact("172.31.255.255").count == 1
    assert redact("192.168.1.1").count == 1
    assert redact("127.0.0.1").count == 1
    assert redact("172.32.0.1").count == 0
    assert redact("8.8.8.8").count == 0
    assert redact("1.1.1.1").count == 0
    assert redact("256.1.1.1").count == 0  # not a valid IP


# --- shape --------------------------------------------------------------------


def test_spans_index_into_returned_text():
    r = redact("from admin@corp.example.org — see logs")
    assert r.count == 1
    s = r.spans[0]
    assert r.text[s.start : s.end] == "[redacted:email]"
    assert s.kind == "email"


def test_multiple_secrets_one_line():
    r = redact("conn postgresql://u:p@10.1.1.1:5432/db failed; paged ops@x.example.com")
    kinds = r.by_kind
    assert kinds.get("connection-string") == 1
    assert kinds.get("email") == 1
    # the private IP is inside the connection string span — not double-counted
    assert "private-ip" not in kinds


def test_empty_and_clean():
    assert redact("").text == ""
    assert redact("just a normal sentence about pods and pools").count == 0
