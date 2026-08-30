# ADR 0013 — Hosted embeddings + reranking (Jina)

- **Status:** Accepted
- **Date:** 2026-08-30
- **Deciders:** Ritvik
- **Supersedes:** the local-model parts of ADR-0002 and ADR-0003 (the hybrid
  pipeline, RRF, the `embed.py` / `rerank.py` seams, and the `retrieve()`
  contract are all unchanged — only *where the models run* changes).

## Context

The deployed dashboard (ADR-0010) started 502-ing on the first retrieval of a
cold container. Measured cause: resident memory.

| loaded | peak RSS |
|---|---|
| Python + FastAPI + openai + psycopg | 77 MB |
| + `bge-small` embedding model (ONNX, ADR-0002) | 303 MB |
| + `ms-marco-MiniLM` reranker (ONNX, ADR-0003) + one rerank pass | **476 MB** |

Render's **free** and **$7 Starter** plans are both **512 MB** (Starter only adds
CPU). 476 MB is 93% of that before request buffers, the psycopg pool, SSE
queues, or a second concurrent run — so a cold instance that loads both ONNX
models under load gets OOM-killed. Because a run is only persisted on success
(ADR-0010), the in-flight run is lost and the dashboard shows Render's edge 502.

The next RAM tier up is Render Standard ($25/mo, 2 GB). The alternative — the one
ADR-0002's own revisit trigger names — is to move the models off the box:
*"reconsider a hosted model behind the same `embed.py` interface, with a
superseding ADR."*

Goal for this change: **stay on the free plan** (portfolio piece, near-zero
traffic) and keep hosting cost at $0.

## Options considered

### A. Render Standard ($25/mo), keep local models

- **For:** zero code change; keeps the "offline / no key" property of ADR-0002.
- **Against:** $25/mo for a demo; doesn't address that two 2022-era tiny models
  are the weakest link in retrieval quality.

### B. Reranker → API, embeddings stay local ($7 Starter)

- Frees ~173 MB → ~303 MB, fits 512 MB with headroom. No re-embed, no migration.
- **Against:** still 303 MB / 512 (59%) — workable but not comfortable; still
  ships `onnxruntime` + a model in the image; still $7/mo; still can't use the
  free plan.

### C. Both embeddings + reranking → Jina API, free plan (chosen)

- Container drops to ~90 MB. `onnxruntime` and both model weights leave the
  image (~200 MB smaller, faster cold start).
- **Jina** covers *both* models with **one key, one provider, one ADR**. A new
  key gets **10M free tokens, no credit card**; then $0.05 / M.
- Quality goes **up**: `jina-embeddings-v5-text-small` (current SOTA sub-1B
  multilingual, 1024-dim) and `jina-reranker-v2-base-multilingual` both clearly
  outrank `bge-small` / `ms-marco-MiniLM-L-6`.
- **Against:** a new secret; ~0.3–0.8s added latency per incident (two API
  round-trips inside `retrieve()`); a dependency on Jina's uptime; the loss of
  "retrieval runs offline". See mitigations below.

## Decision

**Option C.** `src/runbook/jina.py` is the single Jina call site (mirroring
`llm.py`): one `httpx.Client`, one retry helper, provider shapes never leak past
the module. It is **synchronous on purpose** — the only callers are `embed.py` /
`rag/rerank.py`, reached from `core/loop.py` via `asyncio.to_thread` (already off
the event loop) and from the sync CLI. Blocking HTTP there is correct.

- **Embeddings:** `jina-embeddings-v5-text-small`, 1024-dim, native (no Matryoshka
  truncation — index size is irrelevant at ~2.1k rows). `embed_query` passes
  `task="retrieval.query"`, `embed_passages` passes `task="retrieval.passage"` —
  the model's retrieval adapters replace `bge-small`'s magic instruction prefix.
- **Reranking:** `jina-reranker-v2-base-multilingual` over the fused top-30. The
  flagship `jina-reranker-v3.5` is a one-line `config.py` swap if a quality gap
  ever shows up in the golden set, at more tokens/call.
- `documents.embedding` becomes `vector(1024)` (migration `0007`). Vectors from
  different models are not comparable, so the migration **nulls every embedding**
  and `runbook embed --all` recomputes the whole corpus. `embedding_model` /
  `embedding_dim` stay coupled in `config.py`.

### The offline-reproducibility trade

ADR-0002 valued running retrieval + its eval offline with no secrets. What
actually changes:

- The **eval suite already needs a real key** (live model calls — ADR-0008).
- The **deterministic test suite already mocks every model call**. `test_jina.py`
  mocks `httpx` (request shape, parsing, retry). `test_embed.py`'s live tests and
  `test_retrieval_quality.py` now `skipif` without a real `JINA_API_KEY` — the
  same pattern they already use for `DATABASE_URL`. **CI stays secretless.**
- So the only real loss is `runbook search` / a real `retrieve()` on a plane.
  Acceptable.

## Consequences

- New: `src/runbook/jina.py`, `migrations/0007_jina_embeddings.sql`,
  `tests/test_jina.py`, `JINA_API_KEY` (`.env`, Render, `.env.example`).
- Removed: `fastembed`, `pgvector` (was unused), the Dockerfile model-bake step,
  `onnxruntime` (transitively). `httpx` promoted to a direct dependency.
- `embed.py` and `rag/rerank.py` shrink to thin wrappers over `jina.py`.
- **Deploy is a breaking schema+model change** — order matters (new code + old
  384-dim DB = pgvector dimension error; old code + migrated DB = vector leg
  empty, full-text carries it, no crash). Sequence: set `JINA_API_KEY` on Render
  → apply `0007` to prod → `runbook embed --all` against prod (~1 min) → push new
  code. Brief full-text-only window between migrate and re-embed.
- **Render:** `plan: free`. Free tier spins down after 15 min idle (30–60s cold
  start); a `.github/workflows/keepwarm.yml` cron pings `/health` to hold it warm.

### Token budget

One-time corpus embed ≈ 489K tokens. Per incident ≈ query embed (~40) + rerank
(query + 30 chunks × ~230 ≈ 7K) ≈ **~7K tokens**. The 10M free pool ⇒ ~1,350
demo incidents, then 1,000 more ≈ $0.35. Effectively free.

### Revisit triggers

- **Free pool drains and paying is unwanted:** move embeddings to Google Gemini's
  *recurring* free tier (`gemini-embedding-001`, 1,500 req/day) behind the same
  `embed.py` seam — another migration + re-embed.
- **Retrieval latency becomes a UX problem:** cache the query embedding (the
  Week 3 semantic-cache slice already needs this) and/or gate rerank by triage
  category.
- **Jina outage correlates with failed runs:** add a local `fastembed` fallback
  behind a flag (re-introduces the RAM cost only on the fallback path).
- **Golden-set hit@3 regresses vs the ADR-0003 baseline:** try
  `jina-reranker-v3.5`, then reconsider the embedding model.

## Evidence

_(to fill in after the prod cutover — `runbook search` on the ADR-0003 cases +
a `runbook eval` groundedness check, before/after.)_
