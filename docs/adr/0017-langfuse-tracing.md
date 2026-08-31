# ADR 0017 — Langfuse tracing

- **Status:** Accepted
- **Date:** 2026-08-31
- **Deciders:** Ritvik

## Context

Runbook had two ways to know it works, and a gap between them:

- **Evals** (`runbook eval`) — a fixed golden set through the real loop, scored
  before a change ships. A *lab* measurement: controlled inputs, repeatable.
- **The audit record** (`incident_runs`, SPEC S6) — one row per real run,
  structured for "what did this run decide / retrieve / propose / get approved".
  A *compliance* view, not a debugging one.

Neither gives a **per-run, drill-down view of the machinery on real traffic**:
which of the ~6–10 model calls was slow, where `$/incident` actually went, what
the model saw in its context window at synthesis time — as an expandable
timeline. That is **LLM observability**, and `SPEC.md` commits to Langfuse for it
in three places ("Langfuse wraps every model and tool call for tracing; a sample
is online-scored"). This ADR covers the **tracing** half. Online scoring
(auto-evaluating a sample of prod runs) is a deliberate follow-up (see *Revisit
if*).

## Decision

### 1. Langfuse Cloud (hobby tier), not self-hosted

Self-hosting Langfuse is another web service + Postgres + ClickHouse to run.
Cloud's free tier (50k units/mo, no card) is ample for a portfolio project.
Same reasoning as ADR-0002 (don't run infra you don't have to) and ADR-0013
(embedding/rerank moved off-box to hosted Jina). Runbook's own infra stays *app +
Neon*; everything else is a hosted dependency behind one call site.

### 2. Hybrid instrumentation, one integration module

- **`src/runbook/obs.py`** is the single seam — mirrors `jina.py` / `llm.py`
  being the one call site for their concern. It owns client setup, the S5 mask
  hooks, and thin `trace()` / `span()` / `flush()` helpers that **no-op when
  tracing is off**.
- **Model calls: auto.** `llm.py` imports its client from `langfuse.openai`
  instead of `openai`. Because `llm.py` is the *only* place model calls happen,
  that one-line swap instruments 100% of them — each becomes a *generation* with
  model, tokens, latency, prompt and completion, with zero per-call-site code.
- **Everything else: a few explicit spans.** `core/loop.py`'s public `diagnose`
  opens the root trace and delegates to `_diagnose`, which carries typed child
  spans around the non-LLM work: `triage`, `retrieve` / `retrieve-memory`
  (`retriever`), `tool-loop` (`agent`), `synthesize` / `synthesize-retry`,
  `guardrail`. Correct observation types drive Langfuse's per-type analytics and
  the Agent Graph. This matches the "explicit loop, no hidden control flow" ethos
  (ADR-0001/0005) — the trace tree reads like the loop.
- The `on_event` / SSE narration (`core/events.py`) is **untouched**. Events are
  point-in-time and load-bearing for the dashboard timeline; spans have duration
  and nesting and are pure telemetry. Coupling them would have made one serve two
  masters.

### 3. A no-op unless configured; traced surfaces are chosen explicitly

`obs.setup()` builds a client only when `langfuse_enabled` *and* both keys are
present. Absent keys ⇒ silent no-op — CI and the deterministic suite set nothing
(and `LANGFUSE_ENABLED=false` in `conftest.py`) and pay nothing. `setup()` is
called by the **CLI `diagnose` command** and the **web app** only. The eval and
red-team runners never call it, so their thousands of `diagnose()` calls emit no
traces — offline-eval tracing is a separate concern for a later slice. Latency
overhead is a background batch-export thread; `flush()` runs in a `finally` in
the CLI (short-lived process) and in the app's lifespan shutdown.

### 4. S5 — redaction before a trace

SPEC S5: *"Secrets and PII are redacted from any text before it reaches a model
provider **or a trace**."* Two layers, both routing through `redact.redact()`:

- **Model-call generations** — `llm._redact_outgoing()` already scrubs every
  outgoing message at the API-call choke point; the `langfuse.openai` wrapper
  captures the *already-scrubbed* messages. Tool results are redacted in
  `loop.py` before they enter history.
- **Structural backstop** — `Langfuse(mask=…)` scrubs every field set through the
  SDK (the root trace input = the alert, span outputs); `Langfuse(mask_otel_spans=…)`
  scrubs the raw OpenAI-instrumentation span attributes (prompt / completion
  text) that the legacy `mask` hook doesn't see. The alert is also redacted
  explicitly before it becomes the trace input.

Verified end-to-end: a run with a planted `postgresql://user:pw@host/db` in the
alert produced a trace where the string appears **nowhere** across ~100 KB of
trace JSON (every prompt, completion, span field) — only `[redacted:connection-string]`.

### 5. Sampling knob, 100% for now

`langfuse_sample_rate` (default `1.0`) is wired to `Langfuse(sample_rate=…)`.
Traffic is trivial (a demo), so everything is traced; the knob exists so the
scaling answer is real, not hand-waved.

### 6. Link the trace to the audit row (id in the DB, URL on the console)

`migrations/0012` adds `incident_runs.langfuse_trace_id` (canonical W3C id, for
`langfuse-cli` / future online-scoring linkage) and `langfuse_trace_url` (the
Langfuse URL, best-effort via `Langfuse.get_trace_url()`). Both nullable — NULL
means tracing was off. `runbook run <id>` and `runbook diagnose` print the URL;
it's for whoever operates the system and has Langfuse access.

**No link from the web dashboard.** The dashboard has no auth (SPEC), and a
Langfuse URL sits behind a project login — useless to a portfolio visitor.
Making individual traces public was tried and dropped: `set_current_trace_as_public()`
is clobbered on ingest by the `langfuse.openai` wrapper (which pins every
generation to the trace and resets trace-level attributes), so it only holds via
an out-of-band `trace-create` ingestion upsert — more moving parts than a
demo-visible link is worth. Tracing stays a *documented* capability (this ADR,
the HowItWorks page, `/decisions`); the live artifact is the console's own
run-anatomy view, which already shows the retrieved context, every tool call, and
the proposal.

**No trace tags.** `propagate_attributes(tags=…)` combined with child spans is
buggy in the current SDK (v4.15), and the only tag worth setting (`diagnose`)
duplicates the trace name. Per-run dimensions (`use_cache`, `use_memory`, `k`) go
in trace `metadata`.

## Consequences

- One new dependency (`langfuse` v4, + OpenTelemetry libs — a few MB; container
  stays well inside the free tier).
- One new module (`obs.py`), two additive nullable columns, no schema-version or
  event-type change (tracing is not narration).
- `llm.py`'s three primitives gained a `trace_name=` kwarg (consumed by the
  wrapper, stripped before the API call) so each generation is named by role
  (`triage` / `tool-turn` / `synthesize` / `guardrail-2nd-pass` / `eval-judge`).
- `core/loop.py`'s `diagnose` is now a thin trace wrapper around `_diagnose`
  (the loop body is unchanged; each `return` path is stamped with the trace
  id/url via the wrapper, not touched individually).
- OpenRouter `:free` model names don't match Langfuse's price table, so per-call
  cost shows as unknown in Langfuse — expected; `core/cost.py`'s paid-price
  `$/incident` is on the trace as metadata/output instead.
- New (tiny) failure surface: a Langfuse outage or a slow `get_trace_url()`. All
  `obs.py` calls are wrapped so telemetry can never break a run; `get_trace_url`
  failure just leaves `langfuse_trace_url` NULL for that run.

## Revisit if

- **Online scoring** (SPEC: "a sample is online-scored") — the `obs.score()` stub
  is the seam. On a sampled fraction of prod runs, run the deterministic scorers
  (grounding / disposition-safety / retrieval-hit) — or the judge — and
  `create_score` against the trace, for a quality-over-time view on real traffic
  and a one-click path from a low-scoring trace to `runbook promote` (ADR-0016).
- **Model completions echoing a secret** — currently covered by `mask_otel_spans`
  doing a blanket string scrub of every exported span attribute. If that proves
  too slow on the export thread, narrow it to the known `gen_ai.*.content` keys.
- **Data residency / a sensitive tenant** (the productionization write-up's
  multi-tenant story) — self-hosting Langfuse becomes worth the infra.
- **A paid model tier or a local triage model** — sampling and per-call cost
  become real levers; wire `sample_rate` down and revisit `$/incident` in Langfuse.
- **Offline-eval observability** — tracing each eval case (behind an
  `origin`-style flag) so a regression is inspectable as a trace, not just a
  scorecard delta.
- **A demo-visible trace** — if the portfolio wants a clickable trace, the clean
  path is an out-of-band `trace-create` ingestion upsert setting `public: true`
  (an SDK-internal `_resources.add_trace_task`), not `set_current_trace_as_public()`;
  or a public Langfuse dashboard rather than per-trace links.
