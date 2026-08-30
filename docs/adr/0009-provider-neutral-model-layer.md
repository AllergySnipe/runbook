# ADR 0009 — Provider-neutral model layer with per-role fallback routing

- **Status:** Accepted
- **Date:** 2026-08-30
- **Deciders:** Ritvik

## Context

The build started on the Anthropic API directly (`claude-haiku-4-5` for
triage/guardrail, `claude-sonnet-5` for the loop + judge), through the single
call site in `llm.py` (ADR-0001).

Three things pushed us off a single hard-wired vendor:

1. **No model-layer lock-in.** The orchestration is deliberately thin and
   provider-agnostic everywhere else; the one place it wasn't was the SDK and the
   model ids. A system that routes an agent loop through an LLM should be able to
   change which model serves which role without a rewrite.
2. **Resilience.** A single provider is a single point of failure — an outage, a
   regional issue, or a rate-limit ceiling stops every run. Per-role **fallback
   chains** turn that into a soft degradation.
3. **Cost efficiency.** The eval discipline (ADR-0008) only works if the full
   30-case set is cheap enough to run often. A metered per-token dependency on the
   most expensive tier works against that.

## Options considered

### A. Stay on the Anthropic SDK, one model per role
- Best raw quality, simplest code (no change).
- Against: vendor lock-in at the model layer; no failover; every `runbook
  diagnose` and every eval run is metered against the top tier.

### B. A single alternative provider's API directly (Groq / Cerebras / Google AI Studio)
- One integration; some have fast, generous tiers.
- Against: swaps one lock-in for another; no cross-provider failover when an
  endpoint is saturated; still a rewrite off the `anthropic` SDK.

### C. An OpenAI-compatible gateway — OpenRouter (chosen)
- One base URL in front of ~100 models from every major provider, all on the
  OpenAI wire format.
- **Model-fallback routing** (`extra_body.models`) — when the primary endpoint
  429s or errors, the gateway transparently tries the next in the list.
- One SDK swap (`anthropic` → `openai`), one base URL; after that, model ids are
  config and roles are independent.
- Against: routing adds a hop; structured-output and tool-calling fidelity varies
  by model and must be pinned per role; shared endpoints can rate-limit under
  load.

### D. Pin dedicated (paid) endpoints for each role
- No shared-pool rate limiting; steady latency.
- This is the **production tuning knob**, not a separate option — under C it's a
  one-line config change per role (drop the cost-optimised id for a dedicated
  one). Left at the cost-optimised roster for now; see Consequences.

## Decision

**Option C.** `llm.py` rewritten on the `openai` async SDK against
`https://openrouter.ai/api/v1`. Model routing is per-role config, each role with
a **fallback chain** (`config.py`):

| role | primary | fallbacks | why |
|---|---|---|---|
| `llm.parse` — triage, guardrail 2nd pass, synthesis | `nvidia/nemotron-3-super-120b-a12b:free` | `z-ai/glm-5.2:free` | nemotron-super reliably enforces a `json_schema` and is rarely saturated; GLM is stronger on prose but its endpoint rate-limits under load |
| `llm.run_turn` — the tool loop | `z-ai/glm-5.2:free` | `minimax/minimax-m3:free`, `minimax/minimax-m2.7:free` | agentic tool-calling ability matters here (GLM: AA Agentic 46); strict JSON does not |
| eval judge | `z-ai/glm-5.2:free` | `nvidia/nemotron-3-super-120b-a12b:free` | a different model family from what usually serves synthesis, to blunt self-preference (ADR-0008) |

The current roster is cost-optimised. Swapping any role to a dedicated endpoint
(option D) is a config change with no code impact.

## What routing through a shared gateway forced into `llm.py`

The mechanical SDK swap was small. Making it *reliable* was not — every item
below came from a real failure during smoke testing:

- **Own the retry loop** (`max_retries=0` on the client). 429/5xx/connection
  errors retry with exponential backoff, honouring `Retry-After`. Shared
  endpoints rate-limit mid-run.
- **`extra_body.models` fallback chain**, de-duped and **capped at 3** (OpenRouter
  rejects longer). When the primary is unavailable the gateway serves from the
  chain.
- **`parse` uses `create` + manual `model_validate_json`**, not the SDK's
  `.parse()` helper — that helper `TypeError`s on OpenRouter's non-standard error
  bodies (a 200 whose payload is a mid-stream provider error, `choices: null`).
  It retries prose / off-schema JSON / no-choice / empty, then raises
  `LLMParseError` (the loop's synthesis catches it → escalate).
- **`provider.require_parameters: true`** on `parse` — only route to endpoints
  that actually honour `response_format`. Without it a model that doesn't support
  it replies in prose and validation blows up.
- **`reasoning.exclude: true`** globally — reasoning still runs (disabling it
  measurably hurt triage accuracy on nemotron) but is kept out of `.content` so
  it never bleeds into structured output.
- `max_tokens` for `parse` raised to 4096 — reasoning models burn the budget
  before emitting the JSON.

`tools.py` schemas moved to OpenAI function format; `core/loop.py` reworked to
consume neutral `llm.Turn` / `llm.ToolRequest` (it never imports `openai`).

## What it cost in quality

Eval scorecard (ADR-0008), Anthropic (Sonnet/Haiku, partial 18/30) → the
gateway-routed roster (full 30, blessed as `baseline.json`):

| metric | target | Anthropic (18) | routed roster (30) |
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
  100% regardless of which model serves. Confirmed across 30 runs.
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

- **Evals are slow and deliberate.** ~7 requests/case against shared endpoints
  meant a 30-case run took ~18–30 min depending on load. Run with `-j 2`. This
  reinforces the ADR-0008 decision (evals are a local, deliberate gate, not
  per-PR CI). `runbook eval --bless <results.json>` blesses a run you already did.
- **The quality floor is a touch lower**, which makes two later slices more
  valuable, not less: prompt tuning against the eval (now), and the Week-4
  fine-tuned triage model (a small model we control beats a shared endpoint on
  both quality and rate limits).
- **Prod (Render) uses the same routing.** `OPENROUTER_API_KEY` replaces
  `ANTHROPIC_API_KEY` in the dashboard. Moving any role to a dedicated endpoint
  is a config change (option D).
- `openai` replaces `anthropic` in the lockfile. `llm.py` stays the single call
  site, so a future third provider is again one file.
