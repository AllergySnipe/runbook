# ADR 0002 — Local embedding model (BGE-small via fastembed)

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** Ritvik
- **Supersedes:** —

## Context

Retrieval (`SPEC.md` "Architecture") is pgvector hybrid search over the `documents`
corpus (~2k chunks: runbooks + postmortems). We need an embedding model to vectorise
both the corpus (once, at ingest) and each incoming alert (per query). Anthropic has
no embeddings API, so the choice is an external embeddings service or a model run
locally.

Constraints that matter here:

1. **`SPEC.md` values reproducibility** — "everything stays reproducible and demo-able
   offline". The sim is fixture-backed; ideally retrieval is too.
2. **Corpus is small and static** — ~2k short chunks, re-embedded only when ingest
   changes. Embedding throughput is a non-issue.
3. **Every new external dependency is a new key, a new failure mode, and a new line
   item** — the project already depends on the Anthropic API.
4. **Retrieval quality has a floor, not a ceiling, that matters** — hit@3 ≥ 0.85 on
   the golden set (`SPEC.md`). A strong small model clears that; we are not chasing
   leaderboard deltas.

## Options considered

### A. Voyage AI (`voyage-3.5-lite`, 1024-dim)

- **For:** Anthropic's recommended embeddings partner; strong retrieval; cheap
  (whole corpus embeds for ~$0.01).
- **Against:** new secret (`VOYAGE_API_KEY`) in local `.env` + Render; a network call
  on every query path, so retrieval now has an external dependency and added p50
  latency; offline dev/eval no longer possible without a stub.

### B. OpenAI (`text-embedding-3-small`, 1536-dim)

- **For:** ubiquitous baseline, cheap, well understood.
- **Against:** same external-dependency and secret cost as A; least differentiated
  choice for a Claude-centred project; largest vector (more index storage on the
  Neon free tier).

### C. Local BGE-small via `fastembed` (chosen)

- `BAAI/bge-small-en-v1.5`, 384-dim, ONNX on CPU, in-process. ~90 MB model,
  downloaded once and cached (baked into the Docker image for prod).
- **For:** no API key, no network on the query path, fully reproducible offline —
  matches value (1); 384-dim keeps the pgvector index small; embeds the whole corpus
  in ~30s on a laptop CPU; `fastembed` is a single focused dependency (ADR-0001
  allows narrow libraries).
- **Against:** retrieval is somewhat weaker than a frontier embeddings model;
  onnxruntime adds image size; CPU embedding of a large *query* burst would be slower
  than a hosted API (irrelevant at this scale, single-tenant).

## Decision

**Option C.** Embeddings run locally with `fastembed` + `BAAI/bge-small-en-v1.5`
(384-dim, cosine). The model is a narrow single-purpose library, consistent with
ADR-0001. `documents.embedding` is `vector(384)` with an HNSW cosine index.

BGE convention is followed: corpus chunks are embedded as-is; queries are embedded
with the `"Represent this sentence for searching relevant passages:"` instruction
prepended (the model card recommends it — `fastembed` does not apply it
automatically for `bge-small`, so `embed_query` does).

## Consequences

- New deps: `fastembed`, `pgvector` (psycopg vector adapter). New module
  `src/runbook/embed.py` — the single embedding call site.
- `runbook embed` backfills `documents.embedding`; re-run after every `runbook ingest`.
- The retrieval slice bakes the model into the Docker image (build-time download) so
  Render has no cold-start fetch and no network dependency at query time.
- Config: `embedding_model`, `embedding_dim` in `config.py` — swapping models means a
  new migration for the dimension + a full re-embed.
- **Revisit trigger:** if golden-set hit@3 sits below target and error analysis points
  at embedding quality (near-duplicate chunks not separating, paraphrase misses),
  reconsider a hosted model (Voyage) behind the same `embed.py` interface, with a
  superseding ADR.
