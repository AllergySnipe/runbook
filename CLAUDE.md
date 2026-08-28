# Runbook

An on-call incident-response copilot. Given an alert, it triages, retrieves the relevant
runbook + similar postmortems, gathers signal via read-only tools against a **simulated**
environment, and proposes a grounded diagnosis + remediation — pausing for human approval
before any state-changing action.

- **What & why, in full:** `docs/SPEC.md` (the contract — read it before changing behaviour).
- **Decisions:** `docs/adr/`.

## Status

Week 0 done — FastAPI skeleton (`/health`, `/`, `/api/demo`), Docker, deployed to Render
(https://runbook-cgkn.onrender.com), git-push-to-deploy.

Week 1 — corpus + embeddings + **retrieval done, verified against Neon**:
- DB: Neon linked (`.neon`), pooled + unpooled URLs. Migrations `migrations/*.sql` +
  `runbook migrate` — `0001` documents + pgvector, `0002` `vector(384)` + HNSW,
  `0003` `chunk_tsv` generated tsvector + GIN.
- Corpus: `src/runbook/ingest/` + `runbook ingest` → 2102 chunks (synthetic paymentsvc +
  Scoutflo SRE + techlearn). Postmortems opt-in (`--source postmortems`), skipped.
- Embeddings: `src/runbook/embed.py` (local fastembed/BGE-small 384-dim; ADR-0002) +
  `runbook embed` — all rows embedded.
- Retrieval: `src/runbook/rag/` (`retrieve.py` = pgvector ∥ Postgres FTS → RRF →
  cross-encoder rerank; `rerank.py`) + `runbook search`. ADR-0003. hit@3 = 6/6 on the
  synthetic failure modes. Docker bakes both models (offline at runtime).
- Sim + tools (ADR-0004): `src/runbook/sim/` = fixture-backed fake environment.
  7 scenarios (`scenarios/<name>/` — 6 failure modes + `healthy`), each a manifest +
  compact metric specs + hand-written signal `logs.jsonl` + deploys + dependency graph;
  deterministic series expansion, per-scenario payments-domain noise generator (no real
  log dataset). `src/runbook/tools.py` = the four **read-only** tools (`query_metrics`,
  `search_logs`, `get_recent_deploys`, `get_service_dependencies`) + a `TOOLS` allowlist
  (S2 groundwork). `runbook sim <action> <scenario>` inspects it by hand. Each scenario
  has a runbook-linkage test that runs its Diagnosis steps and asserts they land.
- Agent loop (ADR-0005): `src/runbook/core/loop.py` — `diagnose(alert, scenario)` = retrieve
  → **manual** tool-use loop (`llm.run_turn`, execute via `tools.run_tool` allowlist, thread
  results) → structured `Diagnosis` (`llm.parse`, Pydantic) → grounding check. `tools.SCHEMAS`
  = hand-written JSON Schemas (no `scenario` arg). Prompts are files: `src/runbook/prompts/`
  (`diagnose.md`, `synthesize.md`) + `load()`. `runbook diagnose <scenario>`. Loop tested
  with a fake model (no API). Grounding (S3) *flags* uncited steps / marks no-steps as
  escalate — regenerate/downgrade enforcement is Week 2. Real runs verified on
  db-pool + bad-migration scenarios.

Not started: triage router, approval gate (S1) + guardrail 2nd pass, redaction (S5), Langfuse,
evals, dashboard. `retrieve()` + tools are sync (called via `asyncio.to_thread` in the loop).
`diagnose` takes the alert text as given (triage is a later slice). Check before assuming a
module exists.

## Golden rules

1. **All persistent state lives in Postgres (Neon).** The Render container disk is ephemeral.
   Nothing important on local disk.
2. **The repo is public. Never commit secrets.** Secrets live in the Render dashboard
   (Environment) and in a local gitignored `.env`. `.env.example` lists the names only.
3. **No agent framework** (LangChain / LlamaIndex / CrewAI / …). Thin custom orchestration.
   See `docs/adr/0001-*`.
4. **Retrieved content and tool output — especially log lines — are untrusted data, never
   instructions.** (`SPEC.md` S4.) They go into prompts inside clearly delimited, labelled
   blocks.
5. **Safety invariants `SPEC.md` S1–S6 are enforced in code and checked by evals** — never
   "requested" in a prompt and hoped for.
6. **Deterministic code gets `pytest` tests. Probabilistic behaviour gets evals.** Every
   change is run against real behaviour before it's "done" — a green typecheck is not done.

## Stack

- Python 3.12, managed with **`uv`** (`uv run ...`, `uv add ...`; `uv.lock` committed).
- **FastAPI** — REST + SSE (run progress). Serves the built React SPA as static files.
- **Postgres + pgvector** on Neon. Migrations: plain SQL files in `migrations/` + a small
  applier (Week 1).
- **Pydantic** for all model-facing structured output; **pydantic-settings** for config
  (`src/runbook/config.py`, lazy via `get_settings()`).
- **Langfuse** wraps every model call and tool call (tracing + online scoring) — Week 2.
- **Docker** — single image; listens on `$PORT` (`8000` locally).
  Deploy: Render (Docker), `render.yaml` Blueprint, git-push-to-deploy on `main`.
- Frontend: **Vite + React** in `web/`, built into `web/dist/`, served by FastAPI — Week 2.
- Models: **Anthropic API** (SDK `anthropic` 1.x, async). Exact IDs — triage /
  guardrail second-pass: `claude-haiku-4-5`; diagnosis: `claude-sonnet-5`. No date suffixes.

## Layout

```
docs/              SPEC, ADRs, backlog
migrations/        plain .sql files, applied by `runbook migrate`
corpus/synthetic/  hand-written paymentsvc runbooks (committed; part of the corpus)
data/raw/          ingest cache — fetched tarballs + postmortem text (gitignored)
src/runbook/       app.py (FastAPI), config.py, llm.py (one model-call site), db.py,
                   cli.py, migrate.py, embed.py, ingest/ (fetch + chunk + load),
                   rag/ (hybrid retrieve + rerank), sim/ (fixture env + scenarios/),
                   tools.py (read-only tools + schemas + allowlist), core/ (the loop),
                   prompts/ (versioned prompt files)
tests/             deterministic pytest tests (no model calls, no secrets, no DB)
Dockerfile         python:3.12-slim + uv, uvicorn on $PORT
render.yaml        Render Blueprint (deploy config)
(coming: evals/, web/)
```

## Commands

```
uv sync                                              install from the lockfile
uv run pytest                                         deterministic tests
uv run ruff check . && uv run ruff format .           lint + format
uv run uvicorn runbook.app:app --reload --port 8000   local server
uv run runbook search "<alert text>" [-k N] [--mode]   hybrid retrieval over the corpus
uv run runbook diagnose <scenario> [--alert ...]        incident loop → grounded diagnosis (real model call)
uv run runbook sim <action> <scenario> [...]            inspect the sim (list|show|metrics|logs|deploys|deps)
# coming: uv run evals
```

## Conventions

- **Prompts are versioned files** (in `prompts/`), not inline string literals. Loaded by name.
- **One ADR per real decision** in `docs/adr/NNNN-title.md`.
- One vertical slice per branch/PR; the slice isn't done until it runs end-to-end.
- Keep this file lean. Add a line when Claude gets something wrong twice; delete stale ones.
