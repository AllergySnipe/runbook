"""`obs` — the Langfuse seam (ADR-0017). Deterministic: no client is ever built
(the suite runs with `LANGFUSE_ENABLED=false`, conftest). These tests pin the
two things that must hold regardless of Langfuse: the **no-op contract** (every
helper is safe and transparent when tracing is off) and the **S5 masking hooks**
(both route through `redact.redact()`).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runbook import obs

SECRET_URL = "connect failed: postgresql://pmt_app:s3cr3t-pw@db-primary.internal:5432/paymentsvc"
SECRET_KEY = "boto3 using AKIA1234567890ABCDEF from env"


@pytest.fixture(autouse=True)
def _reset_obs():
    obs._reset()
    yield
    obs._reset()


def _settings(**over):
    base = {
        "langfuse_enabled": True,
        "langfuse_public_key": "pk-lf-x",
        "langfuse_secret_key": "sk-lf-x",
        "langfuse_base_url": "https://cloud.langfuse.com",
        "langfuse_sample_rate": 1.0,
        "langfuse_environment": "development",
    }
    base.update(over)
    return SimpleNamespace(**base)


# --- no-op contract -------------------------------------------------------


def test_disabled_before_setup():
    assert obs.enabled() is False


def test_setup_noop_when_kill_switch_off(monkeypatch):
    monkeypatch.setattr(obs, "get_settings", lambda: _settings(langfuse_enabled=False))
    obs.setup()
    assert obs.enabled() is False


def test_setup_noop_without_keys(monkeypatch):
    monkeypatch.setattr(obs, "get_settings", lambda: _settings(langfuse_public_key=""))
    obs.setup()
    assert obs.enabled() is False


def test_trace_is_transparent_when_off():
    with obs.trace("diagnose", input={"alert": "x"}, metadata={"k": 4}) as tr:
        assert tr.trace_id is None
        assert tr.trace_url is None
        tr.update_output({"disposition": "auto"})  # must not raise


def test_span_is_transparent_when_off():
    with obs.trace("diagnose") as _tr, obs.span("retrieve", as_type="retriever") as s:
        s.update(output=["doc-a"])  # must not raise


def test_flush_and_score_safe_when_off():
    obs.flush()
    obs.score("grounding_ok", 1.0, trace_id="abc")  # both no-ops, no raise
    # online scoring (ADR-0018) passes a data_type and, for `disposition`, a str value
    obs.score("safety-invariants", 0.0, trace_id="abc", data_type="BOOLEAN", comment="S1 broke")
    obs.score("disposition", "escalate", trace_id="abc", data_type="CATEGORICAL")


# --- S5: masking hooks route through redact() ----------------------------


def test_mask_redacts_strings_and_walks_containers():
    assert "s3cr3t-pw" not in obs._mask(data=SECRET_URL)
    walked = obs._mask(data={"alert": SECRET_KEY, "n": 3, "items": [SECRET_URL]})
    assert "AKIA1234567890ABCDEF" not in walked["alert"]
    assert walked["n"] == 3
    assert "s3cr3t-pw" not in walked["items"][0]


def test_mask_passes_clean_text_through_unchanged():
    clean = "p99 latency on /charges climbed to 1200ms after the 14:02 deploy"
    assert obs._mask(data=clean) == clean


def test_mask_otel_spans_patches_secret_attributes():
    ident = ("trace-1", "span-1")
    span = SimpleNamespace(
        attributes={
            "gen_ai.prompt.0.content": SECRET_URL,
            "gen_ai.completion.0.content": "rolled back cleanly",
            "http.status_code": 200,
        }
    )
    params = SimpleNamespace(spans={ident: span})

    result = obs._mask_otel_spans(params=params)

    patch = result.span_patches[ident]
    assert "s3cr3t-pw" not in patch.set_attributes["gen_ai.prompt.0.content"]
    # only the attribute that actually changed is patched
    assert set(patch.set_attributes) == {"gen_ai.prompt.0.content"}


def test_mask_otel_spans_returns_none_when_nothing_sensitive():
    span = SimpleNamespace(attributes={"gen_ai.completion.0.content": "all clear"})
    params = SimpleNamespace(spans={("t", "s"): span})
    assert obs._mask_otel_spans(params=params) is None
