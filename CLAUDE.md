# Runbook

An on-call incident-response copilot. Given an alert, it triages, retrieves the relevant
runbook + similar postmortems, gathers signal via read-only tools against a **simulated**
environment, and proposes a grounded diagnosis + remediation — pausing for human approval
before any state-changing action.

- **What & why, in full:** `docs/SPEC.md` (the contract — read it before changing behaviour).
- **Decisions:** `docs/adr/`.

## Status

**Weeks 0–2 done + deployed** (`main` HEAD, https://runbook-cgkn.onrender.com, Render **free**
plan): Neon + `migrations/0001`–`0007`, `ingest`/`embed`, `rag/` hybrid retrieve+rerank,
`sim/` + `tools.py`, `core/` loop → triage → guardrail → approval gate, golden eval set
(30/30 blessed), dashboard REST+SSE + React SPA, OpenRouter LLM layer (ADRs 0002–0010).
Deterministic CI.

**Week 3 done:** redaction/S5 (`redact.py`, ADR-0011) · log-injection red-team
(`src/runbook/redteam/` + `runbook redteam` CLI, ADR-0012; not in CI) · **hosted retrieval
models** — embeddings + reranking on **Jina** (`src/runbook/jina.py`, one call site; ADR-0013
supersedes the local-model parts of 0002/0003), `jina-embeddings-v5-text-small` (1024-dim) +
`jina-reranker-v2-base-multilingual`. `migrations/0007` → `vector(1024)`, corpus re-embedded.
Container ~476 MB → ~90 MB; needs `JINA_API_KEY`. **Verified on prod** (`run_49b3e90b`).
· **semantic cache + `$/incident` + routing** (ADR-0014): `alert_cache` (`migrations/0008`,
`vector(1024)`) — a near-duplicate proceeding alert within 0.97 cosine + 1 h TTL reuses the
triage + retrieval prefix (never the diagnosis); `core/cache.py`, opt-in via
`diagnose(use_cache=)` (CLI + dashboard yes, evals/red-team no). Alert embedding computed
once, reused for the lookup + the retrieval vector leg. `llm.Usage.model` (served model, per
the fallback chain) → `usage["by_model"]` → `core/cost.py` `$/incident` at paid list prices →
`incident_runs.cost_usd` (`migrations/0009`) + `GET /api/stats` (p50/p95 latency, cache-hit
rate). `_route_loop_model`: confident `known-runbook` → cheaper loop chain (payoff latent on
the free tier). Persist-at-start fix: `record_run_start` stub + `mark_run_failed` — a crashed
dashboard run is `failed`, not a 404. `record_run` is now an upsert.

**Week 3 not started:** incident memory + red-team→eval flywheel · Langfuse tracing ·
`/security` dashboard page. Nothing executes on approval — no state-changing tools.
`retrieve()` + tools + `cache.py` are sync (blocking HTTP runs inside, only via
`asyncio.to_thread` / the CLI). Check before assuming a module exists.

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
- **Langfuse** — planned for Week 3 (per-run trace inspection, online scoring, $/incident).
  Not built yet; the eval set + per-run `usage` accounting cover the "is it working / what
  does it cost" signal for the CLI phase.
- **Docker** — single image; listens on `$PORT` (`8000` locally).
  Deploy: Render (Docker), `render.yaml` Blueprint, git-push-to-deploy on `main`.
- Frontend: **Vite + React + Tailwind + react-router** in `web/`, built into `web/dist/`,
  served by FastAPI as the SPA (ADR-0010). Live run progress over **SSE**.
- Models: **OpenRouter** (OpenAI-compatible, SDK `openai` async) — ADR-0009. Per-role chains
  (`config.py`): triage / structured-parse workhorse = `nvidia/nemotron-3-super-120b-a12b:free`
  (reliably enforces `json_schema`); tool loop (`diagnosis_model`) = `z-ai/glm-5.2:free` →
  `loop_fallbacks` (MiniMax m3, m2.7); eval judge = `z-ai/glm-5.2:free` → nemotron. `llm.py` is
  the one call site; it owns 429/5xx retry and walks each chain via `extra_body.models`.
- Retrieval models: **Jina** (embeddings + reranking, hosted) — ADR-0013. `jina.py` is the one
  call site (sync `httpx`, own retry). `jina-embeddings-v5-text-small` (1024-dim, `task`
  adapters) + `jina-reranker-v2-base-multilingual`. Needs `JINA_API_KEY` (10M free tokens).

## Layout

```
docs/              SPEC, ADRs, backlog
migrations/        plain .sql files, applied by `runbook migrate`
corpus/synthetic/  hand-written paymentsvc runbooks (committed; part of the corpus)
data/raw/          ingest cache — fetched tarballs + postmortem text (gitignored)
src/runbook/       app.py (FastAPI), config.py, llm.py (one model-call site), db.py,
                   cli.py, migrate.py, embed.py, ingest/ (fetch + chunk + load),
                   rag/ (hybrid retrieve + rerank), sim/ (fixture env + scenarios/),
                   tools.py (read-only tools + schemas + allowlist),
                   core/ (triage + loop + guardrail + store + events), prompts/ (versioned),
                   evals/ (golden set + scorers + judge + runner + report + baseline.json),
                   redteam/ (log-injection harness: attacks + inject + ablate + detect + report),
                   web_api.py (REST + SSE — the dashboard backend)
web/               Vite + React + Tailwind SPA; `npm run build` → web/dist/ (served by app.py).
                   src/{layouts,routes,components,content,lib}; components/evidence/ = native
                   tool-result rendering; content/glossary.js = the inline <Term> glossary
tests/             pytest — deterministic by default (no model calls, no secrets);
                   *_integration.py + retrieval-quality skip without database_url / real JINA_API_KEY
.github/workflows/ ci.yml — ruff + deterministic pytest on every push (no secrets);
                   keepwarm.yml — cron ping to /health (free-tier anti-spin-down)
Dockerfile         node:20 build stage (web/dist) + python:3.12-slim + uv, uvicorn on $PORT
render.yaml        Render Blueprint (deploy config)
```

## Commands

```
uv sync                                              install from the lockfile
uv run pytest                                         deterministic tests
uv run ruff check . && uv run ruff format .           lint + format
uv run uvicorn runbook.app:app --reload --port 8000   local server
uv run runbook search "<alert text>" [-k N] [--mode]   hybrid retrieval over the corpus
uv run runbook triage "<alert>"                         classify an alert into a handling lane (real model call)
uv run runbook diagnose <scenario> [--alert ...]        incident loop → diagnosis + disposition; persists a run
uv run runbook runs [--status S] [-n N]                 list recent incident runs
uv run runbook run <id>                                 show one run (the audit record)
uv run runbook approve <id> [--step N] [--by NAME]      approve a run's pending state-changing steps
uv run runbook reject <id> --note "why" [--by NAME]     reject a run (whole run → rejected)
uv run runbook feature <id> [--unfeature]               mark a run as a curated dashboard exemplar
uv run runbook sim <action> <scenario> [...]            inspect the sim (list|show|metrics|logs|deploys|deps)
uv run runbook eval [--scenario N] [--no-judge] [-j N]  golden eval set → real loop → scorecard vs baseline
uv run runbook eval --update-baseline                   on a clean run, re-bless evals/baseline.json
uv run runbook eval --bless eval-results/<run>.json      bless a prior --json run without re-running
uv run runbook redteam [--condition both] [-j N] [--json P]  log-injection red-team → ASR, baseline vs hardened

cd web && npm install && npm run dev                    dashboard dev server (:5173, proxies /api → :8000)
cd web && npm run build                                 build the SPA into web/dist/ (app.py then serves it)
```

## Conventions

- **Prompts are versioned files** (in `prompts/`), not inline string literals. Loaded by name.
- **One ADR per real decision** in `docs/adr/NNNN-title.md`.
- One vertical slice per branch/PR; the slice isn't done until it runs end-to-end.
- Keep this file lean. Add a line when Claude gets something wrong twice; delete stale ones.
