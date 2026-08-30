# Runbook

An on-call incident-response copilot. Given an alert, it triages, retrieves the relevant
runbook + similar postmortems, gathers signal via read-only tools against a **simulated**
environment, and proposes a grounded diagnosis + remediation — pausing for human approval
before any state-changing action.

- **What & why, in full:** `docs/SPEC.md` (the contract — read it before changing behaviour).
- **Decisions:** `docs/adr/`.

## Status

Week 0–1 done — FastAPI + Render deploy; Neon + `migrations/0001`–`0004`; `ingest/` (2102
chunks) + local `embed.py` (ADR-0002); `rag/` hybrid retrieve + rerank (ADR-0003); `sim/`
fixture env + 7 scenarios + `tools.py` 4 read-only tools + allowlist (ADR-0004); `core/loop.py`
manual tool-use loop → structured `Diagnosis` (ADR-0005).

Week 2 — CLI incident loop is feature-complete: `core/triage.py` (ADR — 4-lane classifier,
short-circuits noise/need-info), `core/guardrail.py` (ADR-0006 — S3 grounding enforcement +
independent action classification + tighten-only 2nd pass → `disposition`), `core/store.py` +
`migrations/0004` (ADR-0007 — persisted approval gate; `compute_status()` pure/unit-tested;
`runbook runs|run|approve|reject`). Golden eval set (ADR-0008 — `src/runbook/evals/`, 30 cases,
hard S1–S3 + soft metrics + reference LLM-judge, real `diagnose()` never persisted, `baseline.json`
regression gate; `runbook eval`). Deterministic CI (`.github/workflows/ci.yml`).

Dashboard (ADR-0010): `web_api.py` exposes the loop over HTTP + SSE — `POST /api/incidents`
(fire-and-forget `asyncio` task, no job queue), `GET /api/incidents(+/{id})`, SSE
`/{id}/events` (replay-then-live), `POST /{id}/approve|reject`, `GET /api/scenarios`. Progress
via `diagnose(on_event=...)` → `core/events.py` (versioned; `None` for CLI/eval — baseline
unaffected). In-memory `_RUNS` registry is the disposable live layer; Postgres is the record.
`web/` = Vite + React + Tailwind + react-router, built to `web/dist/`, served by `app.py` as
the SPA (mounted after the API) when present. Dev: `uvicorn` + `cd web && npm run dev` (proxies
`/api`). Dockerfile has a `node:20` build stage.

LLM provider = **OpenRouter free models** (ADR-0009). `llm.py` on the `openai` SDK: neutral
`Turn`/`Usage`/`ToolRequest`, own 429/5xx retry, per-role model fallback chains
(`extra_body.models`, capped at 3), `parse` via `create` + manual validation. Config chains
(`config.py`): parse = `nvidia/nemotron-3-super-120b-a12b:free`, tool loop = `z-ai/glm-5.2:free`
→ MiniMax, judge = GLM → nemotron. Blessed baseline: 30/30, deterministic metrics 1.00, judge
0.91, hard checks clear. `OPENROUTER_API_KEY` in `.env` + Render.

Not started: incident memory, Langfuse tracing, redaction (S5). Nothing is executed on
approval — no state-changing tools. The dashboard's post-resolution root-cause note is captured
(`resolve_approvals(note=...)`) but not yet fed to a new eval case / incident memory. `retrieve()`
+ tools are sync (via `asyncio.to_thread`). Check before assuming a module exists.

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
- Models: **OpenRouter** (OpenAI-compatible, SDK `openai` async), **free `:free` models** —
  ADR-0009. Per-role chains (`config.py`): triage / structured-parse workhorse =
  `nvidia/nemotron-3-super-120b-a12b:free` (reliably enforces `json_schema` on the free tier);
  tool loop (`diagnosis_model`) = `z-ai/glm-5.2:free` → `loop_fallbacks` (MiniMax m3, m2.7);
  eval judge = `z-ai/glm-5.2:free` → nemotron. `llm.py` is the one call site; it owns 429/5xx
  retry (free tier = 20 req/min) and walks each chain via `extra_body.models`.

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
                   web_api.py (REST + SSE — the dashboard backend)
web/               Vite + React + Tailwind SPA; `npm run build` → web/dist/ (served by app.py)
tests/             pytest — deterministic by default (no model calls, no secrets);
                   *_integration.py skip themselves without a configured database_url
.github/workflows/ ci.yml — ruff + deterministic pytest on every push (no secrets)
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
uv run runbook sim <action> <scenario> [...]            inspect the sim (list|show|metrics|logs|deploys|deps)
uv run runbook eval [--scenario N] [--no-judge] [-j N]  golden eval set → real loop → scorecard vs baseline
uv run runbook eval --update-baseline                   on a clean run, re-bless evals/baseline.json
uv run runbook eval --bless eval-results/<run>.json      bless a prior --json run without re-running

cd web && npm install && npm run dev                    dashboard dev server (:5173, proxies /api → :8000)
cd web && npm run build                                 build the SPA into web/dist/ (app.py then serves it)
```

## Conventions

- **Prompts are versioned files** (in `prompts/`), not inline string literals. Loaded by name.
- **One ADR per real decision** in `docs/adr/NNNN-title.md`.
- One vertical slice per branch/PR; the slice isn't done until it runs end-to-end.
- Keep this file lean. Add a line when Claude gets something wrong twice; delete stale ones.
