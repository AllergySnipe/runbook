"""Triage — the plumbing (alert normalisation, result properties, the model-call
wiring) is deterministic and covered here with a fake model. Whether the *real*
classifier picks the right lane is a manual check now and an eval in Week 2.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from runbook import llm
from runbook.core.triage import TriageResult, _normalise_alert, triage

# --- _normalise_alert ------------------------------------------------------


def test_free_text_passes_through():
    out = _normalise_alert("payments p99 is like 3s, still climbing")
    assert out.startswith("Free-text incident report:")
    assert "payments p99 is like 3s" in out


def test_non_alertmanager_json_is_treated_as_text():
    out = _normalise_alert('{"foo": "bar"}')
    assert out.startswith("Free-text incident report:")
    assert '"foo": "bar"' in out


def _alertmanager_payload(status="firing", **alert_overrides):
    alert = {
        "status": status,
        "labels": {
            "alertname": "PaymentsvcP99LatencyHigh",
            "service": "paymentsvc",
            "severity": "critical",
        },
        "annotations": {
            "summary": "p99 on POST /charges above 2s for 5m",
            "runbook_url": "https://runbooks.example/paymentsvc/latency",
        },
        "startsAt": "2026-08-29T14:03:10Z",
        "endsAt": "0001-01-01T00:00:00Z",
    }
    alert.update(alert_overrides)
    return {
        "status": status,
        "commonLabels": {
            "alertname": "PaymentsvcP99LatencyHigh",
            "service": "paymentsvc",
            "severity": "critical",
        },
        "commonAnnotations": {"summary": "p99 on POST /charges above 2s for 5m"},
        "alerts": [alert],
    }


def test_alertmanager_dict_is_flattened():
    out = _normalise_alert(_alertmanager_payload())
    assert "Alertmanager payload" in out
    assert "status=firing" in out
    assert "PaymentsvcP99LatencyHigh" in out
    assert "service=paymentsvc" in out
    assert "severity=critical" in out
    assert "p99 on POST /charges above 2s" in out
    assert "runbook_url: https://runbooks.example/paymentsvc/latency" in out


def test_alertmanager_json_string_is_flattened_same_as_dict():
    payload = _alertmanager_payload()
    assert _normalise_alert(json.dumps(payload)) == _normalise_alert(payload)


def test_flap_signal_survives_normalisation():
    out = _normalise_alert(
        _alertmanager_payload(
            status="resolved", startsAt="2026-08-29T14:03:10Z", endsAt="2026-08-29T14:03:40Z"
        )
    )
    assert "status=resolved" in out
    assert "startsAt: 2026-08-29T14:03:10Z" in out
    assert "endsAt: 2026-08-29T14:03:40Z" in out


# --- TriageResult properties --------------------------------------------------


@pytest.mark.parametrize(
    "category, proceed, low_prior",
    [
        ("known-runbook", True, False),
        ("novel-incident", True, True),
        ("noise-or-flapping", False, False),
        ("need-more-info", False, False),
    ],
)
def test_result_properties(category, proceed, low_prior):
    r = TriageResult(category=category, rationale="x", confidence="high")
    assert r.proceed is proceed
    assert r.low_prior is low_prior


# --- triage() wiring ---------------------------------------------------------


def _run(monkeypatch, alert, category="known-runbook"):
    async def fake_parse(messages, *, schema, **kw):
        assert schema is TriageResult
        return (
            TriageResult(category=category, rationale="fake", confidence="high"),
            SimpleNamespace(input_tokens=20, output_tokens=10),
        )

    monkeypatch.setattr(llm, "parse", fake_parse)
    return asyncio.run(triage(alert, model="fake-model"))


LABELLED_ALERTS = [
    ("PaymentsvcP99LatencyHigh — p99 on /charges above 2s for 5m", "known-runbook"),
    ("charge_success_rate dropped, acquirer-gw p95 spiking", "known-runbook"),
    ("customers double-charged in the last 20 min, ongoing", "known-runbook"),
    ("fraud-scoring sidecar 503s, charges failing closed", "novel-incident"),
    ("brand-new dependency 'tax-svc' timing out on every call", "novel-incident"),
    ("PaymentsvcP99LatencyHigh resolved after 25s", "noise-or-flapping"),
    ("Watchdog always-firing pipeline heartbeat", "noise-or-flapping"),
    ("something seems off with payments idk", "need-more-info"),
]


@pytest.mark.parametrize("alert, expected", LABELLED_ALERTS)
def test_triage_returns_the_classified_category(monkeypatch, alert, expected):
    result = _run(monkeypatch, alert, category=expected)
    assert result.category == expected
    assert result.proceed == (expected in ("known-runbook", "novel-incident"))


def test_triage_accepts_a_dict_payload(monkeypatch):
    result = _run(monkeypatch, _alertmanager_payload(), category="known-runbook")
    assert result.category == "known-runbook"
