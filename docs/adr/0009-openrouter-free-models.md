# ADR 0009 — OpenRouter free models: the LLM provider

- **Status:** Accepted
- **Date:** 2026-08-30
- **Deciders:** Ritvik

## Context

The build ran on the Anthropic API (`claude-haiku-4-5` for triage/guardrail,
`claude-sonnet-5` for the loop + judge). The first full eval run (ADR-0008) hit
the account's credit balance at case 18/30 — ~$3.50 for a partial run, and every
future eval / dev iteration would keep spending real money.

This is a portfolio project. The constraint that matters is **$0 recurring
cost**, not latency or throughput. So: move to free models.

## Options considered

### A. Stay on Anthropic, spend carefully
- Best quality, simplest code (no change).
- Against: every `runbook diagnose` and every eval run costs money; the whole
  point of the eval discipline is to run it often. A metered dependency
  undermines that.

### B. A single free provider's API directly (Groq / Cerebras / Google AI Studio)
- One integration, generous free tiers on some.
- Against: locks the model choice to one vendor's roster; no failover when a
  free endpoint is saturated; still a rewrite off the `anthropic` SDK.

### C. OpenRouter, free `:free` models (chosen)
- One OpenAI-compatible gateway in front of ~20 free models from many providers.
- **Model-fallback routing** (`models: [...]`) — when one free endpoint 429s,
  the gateway tries the next. Essential: each `:free` model has exactly one
  provider endpoint on a shared pool, and they 429 constantly.
- One SDK swap (`anthropic` → `openai`), one base URL, then model ids are config.
- Against: free endpoints are slow, rate-limited (20 req/min; 1000 req/day with
  ≥$10 ever spent), and lower quality than Sonnet. Structured-output and
  tool-calling support varies by model and isn't guaranteed even when advertised.

### D. OpenRouter, cheapest *paid* models (GLM 5.2 ≈ $0.33/$1.03 per Mtok)
- ~1/10th of Sonnet; a full eval run ≈ $0.20. No rate-limit fight.
- Rejected for now — the brief is "free". Kept as the obvious escape hatch if the
  free tier proves unworkable (it's a one-line config change).

## Decision

**Option C.** `llm.py` rewritten on the `openai` async SDK against
`https://openrouter.ai/api/v1`. Model routing is per-role config with a
**fallback chain** per role (`config.py`):

| role | primary | fallbacks | why |
|---|---|---|---|
| `llm.parse` — triage, guardrail 2nd pass, synthesis | `nvidia/nemotron-3-super-120b-a12b:free` | `z-ai/glm-5.2:free` | nemotron-super reliably enforces a json_schema on the free tier and is rarely saturated; GLM is smarter but its one free endpoint 429s almost constantly |
| `llm.run_turn` — the tool loop | `z-ai/glm-5.2:free` | `minimax/minimax-m3:free`, `minimax/minimax-m2.7:free` | agentic ability matters here (GLM: AA Agentic 46); strict JSON does not |
| eval judge | `z-ai/glm-5.2:free` | `nvidia/nemotron-3-super-120b-a12b:free` | a different family from what usually serves synthesis (nemotron), to blunt self-preference (ADR-0008) |

## What the free tier forced into `llm.py`

The mechanical SDK swap was small. Making it *reliable* was not — every item
below came from a real failure during smoke testing:

- **Own the retry loop** (`max_retries=0` on the client). 429/5xx/connection
  errors retry with exponential backoff, honouring `Retry-After`. The free pool
  429s mid-run routinely.
- **`extra_body.models` fallback chain**, de-duped and **capped at 3** (OpenRouter
  rejects longer). When the primary 429s the gateway serves from the chain.
- **`parse` uses `create` + manual `model_validate_json`**, not the SDK's
  `.parse()` helper — that helper `TypeError`s on OpenRouter's non-standard error
  bodies (a 200 whose payload is a mid-stream provider error, `choices: null`).
  It retries prose / off-schema JSON / no-choice / empty, then raises
  `LLMParseError` (the loop's synthesis catches it → escalate).
- **`provider.require_parameters: true`** on `parse` — only route to endpoints
  that actually honour `response_format`. Without it a free model cheerfully
  replies in prose and validation blows up.
- **`reasoning.exclude: true`** globally — reasoning still runs (disabling it
  measurably hurt triage accuracy on nemotron) but is kept out of `.content` so
  it never bleeds into structured output.
- `max_tokens` for `parse` raised to 4096 — reasoning models burn the budget
  before emitting the JSON.

`tools.py` schemas moved to OpenAI function format; `core/loop.py` reworked to
consume neutral `llm.Turn` / `llm.ToolRequest` (it never imports `openai`).

## What it cost in quality

Eval scorecard (ADR-0008), Anthropic (Sonnet/Haiku, partial 18/30 — the run that
hit the credit balance) → OpenRouter free (full 30, blessed as `baseline.json`):

| metric | target | Anthropic (18) | OpenRouter free (30) |
|---|---|---|---|
| triage_accuracy | 0.90 | 1.00 | **1.00** |
| triage_incident_recall | 0.95 | 1.00 | **1.00** |
| retrieval_hit_at_3 | 0.85 | 1.00 | **1.00** |
| failure_mode_exact | 0.80 | 1.00 | **1.00** |
| disposition_match | 0.85 | 1.00 | **1.00** |
| judge_mean_norm | 0.80 | 0.94 | **0.91** |
| judge_pass_rate | 0.85 | 1.00 | **0.96** |
| hard checks (S1–S3) | 100% | clear | **clear** |

**The quality cost is small and confined to the diagnosis narrative.** Every
deterministic metric held at 1.00: triage routing, retrieval, the runbook
`failure_mode` mapping, and the auto/needs-approval/escalate disposition. Only
the LLM-judge score on root-cause *prose* dropped — 0.94 → 0.91 — and it stays
comfortably above the 0.80 target.

Notes:
- Retrieval is model-independent (local embeddings + Neon, ADR-0002/0003) — 1.00
  by construction.
- The hard S1–S3 checks are enforced in code, not by the model, so they stay at
  100% regardless of which model serves. Confirmed across 30 free-model runs.
- **Judge non-determinism is visible.** `bad-migration/paraphrase-1` scored 5 in
  one run and 2 in the next — same case, same prompt. This is why the report
  reads the *mean over the set* and the baseline carries a ±0.05 tolerance
  (ADR-0008). `judge_pass_rate` (fraction ≥ 3) is the steadier signal: 0.96.
- Two judge=2 cases in the first run were a **label bug**, not a model failure —
  the diagnosis model correctly read a specific panic string from the sim logs
  (`nil pointer dereference … field 'occurred_at'`) that the case's
  `reference_root_cause` didn't mention, so the judge penalised a *more accurate*
  answer. Fixed the reference; the cases now score 5. (Lesson from ADR-0008,
  re-learned: references must match what the sim actually contains.)

## Consequences

- **Evals are slow and deliberate.** 20 req/min × ~7 requests/case ⇒ a 30-case
  run took ~18 min fresh and ~30 min once the day's request budget was partly
  spent (the shared free pool 429s harder). Run with `-j 2`. This reinforces the
  ADR-0008 decision (evals are a local, deliberate gate, not per-PR CI).
  `runbook eval --bless <results.json>` blesses a run you already did without
  paying for another.
- **The quality floor is lower**, which makes two later slices more valuable, not
  less: prompt tuning against the eval (now), and the Week-4 fine-tuned triage
  model (a small model we control beats a shared free endpoint on both quality
  and rate limits).
- **Prod (Render) runs the same free models.** `OPENROUTER_API_KEY` replaces
  `ANTHROPIC_API_KEY` in the dashboard. Acceptable for a demo; a real deployment
  would use option D or a paid tier.
- The escape hatch (option D) is `diagnosis_model = "z-ai/glm-5.2"` (drop
  `:free`) + fund the account — no code change.
- `openai` replaces `anthropic` in the lockfile. `llm.py` stays the single
  call site, so a future third provider is again one file.
