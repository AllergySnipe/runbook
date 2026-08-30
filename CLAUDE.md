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

**Week 3 done + deployed:** redaction/S5 (`redact.py`, ADR-0011) · log-injection red-team
(`redteam/` + `runbook redteam`, ADR-0012; not in CI) · hosted retrieval on **Jina**
(`jina.py`, `jina-embeddings-v5-text-small` 1024-dim + `jina-reranker-v2`, ADR-0013,
`migrations/0007`; container ~476→~90 MB; needs `JINA_API_KEY`) · **semantic cache +
`$/incident` + routing** (ADR-0014, `migrations/0008`–`0009`): `core/cache.py` — a re-fired
alert within 0.97 cosine + 1 h TTL reuses the triage + retrieval prefix (never the
diagnosis), opt-in via `diagnose(use_cache=)` (CLI/dashboard yes, evals/red-team no), alert
embedding computed once for lookup + retrieval; `core/cost.py` `$/incident` from
`usage["by_model"]` (keyed on `llm.Usage.model`, the served model) at paid list prices, on
`incident_runs.cost_usd` + `GET /api/stats` (p50/p95 latency, cache-hit rate);
`_route_loop_model` sends confident `known-runbook` to a cheaper loop chain (payoff latent on
the free tier); persist-at-start (`record_run_start` stub + `mark_run_failed`, `record_run`
upserts) — a crashed dashboard run is `failed`, not a 404. Prod-verified (`run_57dca911`).

**Week 3 — incident memory + the flywheel** (ADRs 0015–0016, `migrations/0010`–`0011`):
`core/memory.py` — after a terminal run a human records the confirmed root cause
(`runbook outcome` / dashboard form → `incident_memory`, append-only, human-confirmed only =
the anti-poisoning guard). `diagnose(use_memory=)` (CLI/dashboard yes, evals/red-team no) adds
a 2nd retrieval leg over `incident_memory`, reusing the alert embedding — similar past
incidents go in the prompt as **context, never a grounding source** (S3 unchanged);
`memory_similarity_floor` 0.88 (calibrated — catches recurrences of the same incident, silent
otherwise). `incident_runs.memories` (S6). `events.SCHEMA_VERSION → 4` (`memory.hit`). Flywheel:
`runbook promote <run_id>` renders a golden `EvalCase` stub from a real run (seeded from the
confirmed outcome, labels TODO — human reviews + commits, never auto-appended). The red-team
half of the flywheel was tried as a CI gate and removed — too noisy to gate on the free tier
(ADR-0016 §2); `runbook redteam` stays a manual point-in-time tool. Prod-verified
(`run_a59ce5c8` memory hit).

**Week 3 — `/security` dashboard page** (done, not yet deployed): `GET /api/redteam` serves a
tracked `src/runbook/redteam/latest.json` snapshot (`redteam-results/` is gitignored → absent
from the image), blessed by `runbook redteam --condition both --bless` (parallel to
`evals/baseline.json`). `web/src/routes/Security.jsx` + `web/src/content/security.js` render ASR
by surface/goal (baseline vs hardened), attacks-that-got-through + containment, defence stack,
residual risks. Narrative canonical in `docs/security/log-injection.md`. 302 tests green locally.

**Week 3 — Langfuse tracing** (ADR-0017, `migrations/0012`): `src/runbook/obs.py` is the one
integration point — a **no-op unless `obs.setup()` ran** (CLI `diagnose` + the web app only;
never evals/red-team). `llm.py` imports its client from `langfuse.openai` → every model call
is auto-traced as a *generation* (named by role via a `trace_name=` kwarg). `core/loop.py`'s
public `diagnose` opens the root trace and delegates to `_diagnose`, which carries typed child
spans (`triage` / `retrieve` / `retrieve-memory` / `tool-loop` / `synthesize` / `guardrail`).
S5: `Langfuse(mask=…, mask_otel_spans=…)` route every trace field through `redact.redact()` —
backstopping `llm._redact_outgoing`. `incident_runs.langfuse_trace_id` + `_trace_url` link the
audit row to the trace; the dashboard IncidentDetail shows a "trace ↗" link. Langfuse **Cloud
hobby tier** (US region), `LANGFUSE_ENVIRONMENT` = development locally / production on Render.
Prod-verified. **Online scoring is not built** (the `obs.score()` stub is the seam).

**Not built:** online scoring on sampled runs. Nothing executes on approval — no state-changing
tools. `retrieve()` + tools + `cache.py` + `memory.py` are sync (blocking HTTP, only via
`asyncio.to_thread` / CLI). Check before assuming a module exists.

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
- **Langfuse** (v4, Cloud hobby tier) — LLM tracing, ADR-0017. One trace per `diagnose()`
  run; `src/runbook/obs.py` is the one call site (no-op without keys / when `setup()` wasn't
  called). Auto-instruments model calls via `langfuse.openai`; manual typed spans for the
  loop's phases. Online scoring not built.
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
src/runbook/       app.py (FastAPI), config.py, llm.py (one model-call site),
                   obs.py (one Langfuse-tracing call site), db.py,
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
uv run runbook redteam [--condition both] [-j N] [--json P] [--bless]  log-injection red-team → ASR, baseline vs hardened (manual; not in CI). --bless freezes redteam/latest.json (the /security page)

cd web && npm install && npm run dev                    dashboard dev server (:5173, proxies /api → :8000)
cd web && npm run build                                 build the SPA into web/dist/ (app.py then serves it)
```

## Conventions

- **Prompts are versioned files** (in `prompts/`), not inline string literals. Loaded by name.
- **One ADR per real decision** in `docs/adr/NNNN-title.md`.
- One vertical slice per branch/PR; the slice isn't done until it runs end-to-end.
- Keep this file lean. Add a line when Claude gets something wrong twice; delete stale ones.
