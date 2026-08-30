# ADR 0014 — Semantic cache, per-model cost, difficulty routing

- **Status:** Accepted
- **Date:** 2026-08-30
- **Deciders:** Ritvik

## Context

Three loosely-related Week-3 items, shipped together because they share the same
seam (`core/loop.py` + `core/store.py` + the alert embedding):

1. **Repeated alerts do the same expensive work.** On-call alerts are bursty and
   near-duplicated — the same page fires many times during one incident, with
   drifting text (current metric value, `startsAt`). Every fire currently costs
   one triage model call, one Jina embedding, two Postgres searches, and one Jina
   rerank before the investigation loop starts (~5–15 s).
2. **`$/incident` was unquantified.** SPEC lists "Cost/latency tracking
   (`$/incident`, p50/p95 time-to-first-suggestion)" as a deliverable. The free
   OpenRouter endpoints bill $0, so there was no number at all.
3. **Every alert uses the strongest agentic model.** A high-confidence
   `known-runbook` alert with an unambiguous runbook to follow doesn't need the
   same model as a novel incident.

## Decision

### 1. A semantic cache for the loop *prefix* (never the diagnosis)

`migrations/0008` adds `alert_cache(alert_norm, embedding vector(1024), triage
jsonb, retrieved jsonb, run_id, created_at)`. `core/cache.py` does a cosine
nearest-neighbour lookup (same HNSW / `vector_cosine_ops` as `documents`); a
prior alert is a **hit** when it clears **both** gates:

- cosine similarity ≥ `cache_similarity_threshold` (**0.97**)
- age ≤ `cache_ttl_s` (**1 hour**)

On a hit, `diagnose()` reuses the cached `TriageResult` and `RetrievedChunk`
list, skipping the triage call, both searches, and the rerank. **The
investigation loop always runs fresh** — only the cheap, safe prefix is cached.

Why the prefix and not the diagnosis: the sim environment moves between two fires
of the same alert (new deploys, changed dependencies), and an approval-gated
system must never serve last hour's remediation for this hour's incident. Same
principle as SSE never becoming load-bearing (ADR-0010): the cache is an
accelerator, never a source of truth.

**Why the gate is deliberately tight.** A false negative just repeats work; a
false positive serves the wrong runbook and triage lane for a *genuinely
different* incident — the on-call equivalent of a misfiled ticket. So the
threshold is set to accept false negatives to push false positives to zero.

**What the cache targets:** a *re-fire* of one alert — same incident, text
drifting only in volatile fields (current value, timestamp, a "(retry)" suffix) —
**not** a reworded description. Calibration
(`scripts/calibrate_cache_threshold.py`, `jina-embeddings-v5-text-small`,
`retrieval.query` task):

| alert pair | n | min | mean | max |
|---|---|---|---|---|
| **near-duplicate** — canonical alert vs. small perturbations of itself | 23 | **0.960** | 0.981 | 0.994 |
| paraphrase — golden set's deliberately-diverse rewordings of one incident | 37 | 0.333 | 0.571 | **0.776** |
| cross-scenario — different failure modes | 288 | 0.217 | 0.440 | 0.751 |

At **0.97**: 21/23 near-duplicates caught (the 2 misses swap `p99`→`p95` /
`above`→`over` — arguably a different alert), **0/37 paraphrases**, **0/325
negative pairs**. The 0.18 gap between near-duplicate min (0.96) and paraphrase
max (0.78) is the safety margin. 0.95 would raise re-fire recall with margin
still intact if that ever matters; 0.97 is the zero-false-positive choice.
Diverse rewordings are correctly *not* cached — that's a job for triage +
retrieval, which are cheap enough to re-run.

**Opt-in.** `diagnose(use_cache=False)` by default; the CLI and the dashboard
pass `True`, the eval suite and the red-team harness never do (each case must
exercise the full path, and two paraphrase cases must not hit each other).
`cache_enabled` in config is the prod kill-switch. Every DB error in `cache.py`
is swallowed with a warning, so the code is safe to deploy before the migration
lands.

**Folded in:** the alert embedding is computed once in `diagnose()` and reused
for both the cache lookup and (on a miss) the retrieval vector leg — `retrieve()`
gained `query_vec=`. Closes the `docs/BACKLOG.md` "cache the query embedding"
item. Jina's ~1e-3 embedding jitter (why `test_embed` asserts cosine > 0.999) is
far below the 0.03 margin between the 0.97 gate and 1.00, so it doesn't threaten
the cache.

### 2. `$/incident` — per-model cost attribution

`llm.Usage` gains `model`, populated from OpenRouter's echoed `resp.model` — the
model that **actually served** the call, which the fallback chain (ADR-0009)
means isn't always the one requested. `core/loop.py` accumulates
`usage["by_model"]` alongside the flat totals (kept for the pre-existing prod
rows + the eval baseline). `core/cost.py::estimate_cost` multiplies each model's
tokens by its **paid list price** (`:free` suffix stripped) — the honest "this
architecture would cost ~$X/incident on production infrastructure" number, not an
invoice. Persisted as `incident_runs.cost_usd` (`migrations/0009`), surfaced on
`/incidents/:id` and in `GET /api/stats`.

**Not counted** (documented gap, each <1% of a run): Jina embedding + rerank
tokens (~$0.0001/run), and the triage call (`triage()` discards its usage).
`RATES` in `cost.py` are approximate 2026-08 list prices — refresh from the
OpenRouter model pages if the number ever needs to be defensible to the cent.

**Latency panel.** `GET /api/stats` reports p50/p95 of `elapsed_s`, not the mean:
LLM latency is heavily right-skewed (429 storms), so the mean describes no actual
run while the percentiles do. Standard SRE practice.

### 3. Difficulty routing (`_route_loop_model`)

`known-runbook` + `confidence == "high"` → the cheaper/faster tool-loop chain
(`fast_loop_model` = MiniMax m3 → …); everything else keeps the full
`diagnosis_model` chain (GLM-5.2 → …). `routing_enabled` gates it.

**The cost/latency payoff is latent.** On the current all-`:free` setup every
model bills $0 and latency is dominated by rate-limit backoff, not model speed —
so routing can't *demonstrate* a win yet. This is policy + plumbing, a real lever
once there's a paid tier or a local triage model (Week 4). The routing shows up
in the audit via `usage.by_model` (which model actually ran), so it needs no new
field or event.

## Consequences

- One new table, two additive columns, `events.SCHEMA_VERSION` → 3 (`cache.hit`).
- `record_run` is now an upsert — it overwrites the `record_run_start` stub the
  dashboard writes at kickoff (the "persist at start, mark `failed` on a crash"
  fix from `docs/BACKLOG.md`; a crashed run no longer 404s).
- `diagnose()` on a cache hit makes **one** Jina call (the lookup embedding) and
  **zero** model calls before synthesis, vs. one embed + one rerank + one triage
  call on a miss.
- New failure mode: a stale/poisoned `alert_cache` row could misroute an alert.
  Mitigations: the 1 h TTL, the 0.97 gate, prefix-only caching, and `cache.py`
  discarding any row whose payload won't deserialise. `alert_cache` is not
  attacker-writable (populated only from `diagnose()`'s own triage + retrieval).

## Revisit if

- The golden set shows a lexical/semantic cache miss that a lower threshold would
  have caught without a false positive → tune `cache_similarity_threshold`, or
  add a dedicated cache-normalisation that strips volatile fields (current
  values, timestamps) before embedding.
- A paid model tier or a local triage model lands → routing and `$/incident`
  become real levers; wire routing into the eval set and A/B it.
- Jina cost stops being a rounding error → thread embed/rerank token counts back
  through `jina.py`.
