"""Langfuse tracing — the single integration point (ADR-0017).

One **trace** per `diagnose()` run. `llm.py` imports its OpenAI client from
`langfuse.openai`, so every model call is auto-captured as a *generation*; this
module adds the root trace plus typed manual spans (`triage` / `retrieve` /
`retrieve-memory` / `tool-loop` / `synthesize` / `guardrail`) around the non-LLM
work, so the trace tree matches how the loop actually runs.

**Contract: a no-op unless configured.** `setup()` builds the client only when
`langfuse_enabled` is set *and* both keys are present; otherwise `trace()` /
`span()` yield inert handles and `flush()` does nothing. Deterministic tests and
CI set no keys (and `LANGFUSE_ENABLED=false`) and pay nothing. `setup()` is
called by the CLI `diagnose` command and the web app only — never by the eval /
red-team runners, so their loop runs emit no traces (offline-eval tracing is a
later slice).

**S5 (redaction before a trace, SPEC).** Two masking hooks, both routing through
`redact.redact()`: `mask` for fields we set through the SDK (trace input, span
output), `mask_otel_spans` for the raw OpenAI-instrumentation span attributes
(prompt / completion text). `llm._redact_outgoing` still scrubs at the model-call
choke point — these are the structural backstop.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from .config import get_settings
from .redact import redact

log = logging.getLogger("runbook.obs")

_client: Any | None = None
_configured = False


# --- S5 masking hooks -------------------------------------------------------


def _mask(*, data: Any, **_kw: Any) -> Any:
    """Legacy `mask` hook — recursively scrub every string set through the SDK
    (trace/span input & output, metadata)."""
    if isinstance(data, str):
        return redact(data).text
    if isinstance(data, dict):
        return {k: _mask(data=v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_mask(data=v) for v in data]
    return data


def _mask_otel_spans(*, params: Any) -> Any:
    """Export-stage hook — scrub every string attribute on every exported span.
    Covers the `langfuse.openai` wrapper's prompt/completion capture, which the
    legacy `mask` hook does not see. Runs on the OTel exporter thread; `redact`
    is pure-regex and fast."""
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    patches: dict[Any, Any] = {}
    for ident, span in params.spans.items():
        changed: dict[str, str] = {}
        for key, val in span.attributes.items():
            if isinstance(val, str) and val:
                scrubbed = redact(val).text
                if scrubbed != val:
                    changed[key] = scrubbed
        if changed:
            patches[ident] = OtelSpanPatch(set_attributes=changed)
    return MaskOtelSpansResult(span_patches=patches) if patches else None


# --- lifecycle -------------------------------------------------------------


def setup() -> None:
    """Configure the global Langfuse client. Idempotent — safe to call from every
    entrypoint. Leaves tracing disabled (a silent no-op) when the kill-switch is
    off or keys are absent, and never raises: telemetry must not break a run."""
    global _client, _configured
    if _configured:
        return
    _configured = True

    s = get_settings()
    if not (s.langfuse_enabled and s.langfuse_public_key and s.langfuse_secret_key):
        log.debug("langfuse tracing disabled (no keys / kill-switch off)")
        return

    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=s.langfuse_public_key,
            secret_key=s.langfuse_secret_key,
            base_url=s.langfuse_base_url,
            sample_rate=s.langfuse_sample_rate,
            environment=s.langfuse_environment,
            mask=_mask,
            mask_otel_spans=_mask_otel_spans,
        )
        log.info("langfuse tracing enabled (%s)", s.langfuse_base_url)
    except Exception:
        log.exception("langfuse setup failed — tracing disabled")
        _client = None


def _reset() -> None:
    """Test hook — forget any configured client so `setup()` runs again."""
    global _client, _configured
    _client, _configured = None, False


def enabled() -> bool:
    return _client is not None


def flush() -> None:
    """Force-send buffered spans. Call before a short-lived process exits."""
    if _client is not None:
        try:
            _client.flush()
        except Exception:
            log.debug("langfuse flush failed", exc_info=True)


# --- trace / span helpers -------------------------------------------------


class _NullSpan:
    """Stand-in yielded by `span()` / used as the root when tracing is off."""

    def update(self, **_kw: Any) -> None:
        pass


@dataclass
class TraceHandle:
    """What `trace()` yields — the trace id / URL for linking to the audit row,
    and `update_output()` to set the trace result at each return path."""

    trace_id: str | None = None
    trace_url: str | None = None
    _root: Any = None

    def update_output(self, output: Any) -> None:
        if self._root is not None:
            try:
                self._root.update(output=output)
            except Exception:
                log.debug("trace update_output failed", exc_info=True)


@contextmanager
def trace(
    name: str,
    *,
    input: Any = None,
    metadata: dict | None = None,
) -> Iterator[TraceHandle]:
    """Root trace for one operation. No-op (yields an inert handle) when tracing
    is off. The root observation's name / input / output become the trace's.
    Per-run dimensions go in `metadata` (no trace tags)."""
    if _client is None:
        yield TraceHandle(_root=_NullSpan())
        return

    handle = TraceHandle()
    with _client.start_as_current_observation(as_type="span", name=name, input=input) as root:
        handle._root = root
        try:
            if metadata:
                root.update(metadata=metadata)
            handle.trace_id = _client.get_current_trace_id()
            handle.trace_url = _client.get_trace_url(trace_id=handle.trace_id)
        except Exception:
            log.debug("langfuse trace attribute set failed", exc_info=True)
        yield handle


@contextmanager
def span(name: str, *, as_type: str = "span", input: Any = None) -> Iterator[Any]:
    """A child observation nested under the current trace/span. `as_type` should
    be the most specific of `span` / `retriever` / `agent` / `tool` / `generation`
    (drives Langfuse's per-type analytics + the Agent Graph). No-op when off."""
    if _client is None:
        yield _NullSpan()
        return
    with _client.start_as_current_observation(as_type=as_type, name=name, input=input) as s:
        yield s


def score(
    name: str, value: float, *, trace_id: str | None = None, comment: str | None = None
) -> None:
    """Attach a score to a trace. Unused in slice 1 (tracing); the seam for
    online scoring (ADR-0017 "Revisit if")."""
    if _client is None:
        return
    try:
        _client.create_score(name=name, value=value, trace_id=trace_id, comment=comment)
    except Exception:
        log.debug("langfuse score failed", exc_info=True)
