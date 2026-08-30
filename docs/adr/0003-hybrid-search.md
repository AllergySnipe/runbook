# ADR 0003 — Hybrid retrieval (vector + full-text + RRF + cross-encoder rerank)

- **Status:** Accepted; **superseded in part by [ADR-0013](0013-hosted-retrieval-models.md)**
  (2026-08-30) — the cross-encoder reranker moved from local `fastembed`/`ms-marco-MiniLM`
  to hosted `jina-reranker-v2-base-multilingual`. The hybrid pipeline, RRF, and
  the `retrieve()` contract are unchanged.
- **Date:** 2026-08-28
- **Deciders:** Ritvik
- **Supersedes:** —

## Context

The retrieval spine (`SPEC.md` "Architecture") turns an incoming alert into the runbook
chunks the agent reasons over. `SPEC.md` sets the bar: **hit@3 ≥ 0.85** on labelled
scenarios, and it names the method — "pgvector **hybrid** + rerank".

We already have pure pgvector search (ADR-0002: BGE-small, 384-dim, HNSW cosine). The
question this ADR settles: is pure vector enough, or do we add full-text and a rerank pass?

Constraints:

1. **Incident queries are token-heavy.** Alert names (`PaymentsvcP99LatencyHigh`), error
   strings (`pool timeout: no connection available after 5000ms`), metric names, config
   keys. A bi-encoder embedding blurs these into "general database trouble"; exact-token
   matching is a different failure mode.
2. **The corpus grows and gets noisier.** Today it's ~2.1k mostly-distinct chunks; the
   danluu postmortems (deferred, flaky links) add thousands of loosely-related passages
   that will crowd the vector neighbourhood.
3. **Reproducible + offline** (ADR-0002 value): no new external service.
4. **Single-tenant, low QPS.** A few hundred ms of extra query latency is affordable.

## Options considered

### A. Pure vector (what we have)

- **For:** simplest; one index; already built and passing hit@3 = 6/6 on the synthetic
  failure modes.
- **Against:** measurably fragile on lexical queries. Example — `"5xx spike after deploy"`:
  vector-only returns three generic Scoutflo application-error pages and **misses both**
  `acquirer-gw-timeouts` and `bad-migration-table-lock` from the top 3. No lever to fix
  this without changing the embedding model.

### B. Hybrid: vector + Postgres full-text, fused with Reciprocal Rank Fusion

- Full-text = a `tsvector` generated column (`0003_fulltext.sql`) + GIN index +
  `websearch_to_tsquery('english', …)` ranked by `ts_rank_cd`.
- **RRF** fuses the two ranked id-lists: `score = Σ 1/(60 + rank)`. Rank-only, so cosine
  distance and `ts_rank` (different scales) never need normalising.
- **For:** recovers exact-token matches (on `"5xx spike after deploy"`, FTS pulls the
  `APICallFailed` page into the fused set that vector alone dropped); cheap (one extra
  index, one extra SQL query); no new dependency.
- **Against:** `'english'` config stems and drops tokens — compound identifiers like
  `container_cpu_cfs_throttled_periods_total` or `redis OOM` return **zero** FTS rows, so
  FTS is silent exactly on some of the queries it was supposed to help. Vector carries
  those. (Revisit trigger below.)

### C. Hybrid + cross-encoder rerank over the fused shortlist (chosen)

- After RRF, re-score the top `retrieve_candidates` (30) with a cross-encoder
  (`Xenova/ms-marco-MiniLM-L-6-v2`, local ONNX via `fastembed`) that reads
  `(query, chunk)` together, then take top `k`.
- **For:** fixes ordering, not just recall. On `"5xx spike after deploy"` the rerank pass
  promotes `acquirer-gw-timeouts.md` to **#1** — the correct runbook, which neither vector
  nor un-reranked hybrid had in the top 3. On `PaymentsvcP99LatencyHigh` it promotes the
  more specific connection-pool chunk over a noisy-neighbour near-miss.
- **Against:** a second ~90 MB model in the image; ~50–150 ms per query for 30 pairs on
  CPU; occasionally reshuffles a marginal #3 (e.g. an RBAC page displacing a weak
  bad-migration chunk on `"webhook delays to merchants"`). Net positive on the cases that
  matter.

## Decision

**Option C.** `runbook.rag.retrieve(query, k, mode="hybrid", rerank=None)`:

1. vector search (top 30) ∥ full-text search (top 30)
2. `rrf_fuse` → fused ranking (pure function, unit-tested)
3. hydrate fused top 30
4. cross-encoder rerank (default on; `settings.rerank_enabled`)
5. return top `k`

`mode="vector"` / `"text"` run a single leg — kept for the CLI and for regression
comparisons like the ones above. Config: `rerank_model`, `retrieve_candidates`,
`rerank_enabled` in `config.py`. Both models bake into the Docker image at build time
(no runtime download, no query-path network — same rationale as ADR-0002).

Full-text uses a **generated** `tsvector` column so ingest needs no extra code.

## Consequences

- New: `migrations/0003_fulltext.sql`, `src/runbook/rag/` (`retrieve.py`, `rerank.py`),
  `runbook search` CLI, `tests/test_rrf.py` (pure), `tests/test_retrieval_quality.py`
  (hit@3 gate, skipped without a DB).
- `retrieve()` is **sync** for now (CLI only). An async variant lands with the tool-loop
  slice that needs it.
- Docker image grows by ~90 MB (cross-encoder weights).
- **Revisit triggers:**
  - If FTS keeps returning nothing for identifier-heavy queries, switch the column to the
    `'simple'` text-search config (no stemming/stopwords) — a new migration + superseding
    note. Measure hit@3 both ways first.
  - If rerank latency becomes a problem at higher QPS, cap `retrieve_candidates` or gate
    rerank behind triage category.
  - Golden-set hit@3 below target with error analysis pointing at embeddings → reconsider a
    hosted embedding model behind `embed.py` (ADR-0002's own revisit trigger).

## Evidence (from verification, 2026-08-28, synthetic corpus)

| query | vector-only top-3 | hybrid+rerank top-3 |
|---|---|---|
| `5xx spike after deploy` | 3× generic Scoutflo error pages (miss) | **acquirer-gw-timeouts**, APICallFailed, MemoryError |
| `PaymentsvcP99LatencyHigh` | db-pool, noisy-neighbour, db-pool | **db-pool, db-pool, noisy-neighbour** (tighter) |
| paraphrased alerts ×6 (`test_retrieval_quality.py`) | — | **hit@3 = 6/6** |
