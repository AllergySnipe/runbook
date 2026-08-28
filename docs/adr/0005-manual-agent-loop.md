# ADR 0005 — The agent loop: a manual loop, not the SDK tool-runner

- **Status:** Accepted
- **Date:** 2026-08-29
- **Deciders:** Ritvik
- **Supersedes:** —

## Context

ADR-0001 chose "thin custom orchestration, no agent framework" but left one thing
open: *how* to run the tool-use loop — the request → execute tools → feed results
back → repeat cycle. Since that ADR was written, the `anthropic` SDK shipped
`client.beta.messages.tool_runner` (with `@beta_tool`), which drives that cycle
for you. This ADR settles whether to use it.

The loop is the spine of the incident flow (`SPEC.md` "Architecture"):

```
retrieve runbook → [model turn → tools → results]* → grounded structured diagnosis
```

and later grows the safety branches — the approval gate (S1), the guardrail
second pass, redaction (S5).

## Options considered

### A. SDK tool-runner (`client.beta.messages.tool_runner`)

- **For:** no loop code; tool schemas generated from typed function signatures;
  per-turn hooks for approval/interception.
- **Against:** it's **beta** — API can change under us, and this is the one path
  we least want churn in. It hides the loop, but ADR-0001's whole argument is
  that *"the approval gate is a `pending_approval` row + an explicit branch in
  the loop, not framework middleware — directly testable against S1."* A hidden
  loop can't hold our branch. Schema generation from docstrings couples schema
  quality to formatting and still needs a hack to hide the `scenario` arg (bound
  by us, not chosen by the model). The `pause_turn` handling has known gaps
  (skill notes: the Python runner exits silently on a paused turn).

### B. Manual loop (chosen)

- A `while` loop in `core/loop.py`: `llm.run_turn()` → inspect `stop_reason` →
  on `tool_use`, run each block through `tools.run_tool()` (which enforces the
  `TOOLS` allowlist, S2) → append `tool_result` blocks → repeat. `end_turn` or an
  iteration cap ends it; a final `llm.parse()` call produces the structured
  `Diagnosis`. ~90 lines.
- Hand-written JSON Schemas in `tools.SCHEMAS` — the model never sees `scenario`;
  descriptions carry the "why" (what the model reads to decide when to call).
- **For:** every line readable and testable; the safety branches (Week 2) drop
  into an `if` in code we own; no beta dependency on the critical path; full
  control of context assembly (the retrieved runbook goes in a delimited
  `<runbook>` block, S4). Tested with a fake model — deterministic coverage of
  allowlist rejection, result threading, the iteration cap, and the grounding
  check, with zero API calls.
- **Against:** we maintain the loop, retry semantics, and `pause_turn` handling
  ourselves (all small); no free tool-schema generation.

## Decision

**Option B — manual loop.** `llm.py` stays the single model-call site (adds
`run_turn` and `parse` primitives); `core/loop.py` owns the loop; `tools.py`
owns the schemas + the allowlisted executor.

## Consequences

- `core/loop.py` — `diagnose(alert, scenario)` → retrieve → loop → synthesize →
  ground-check → `DiagnoseResult`. `runbook diagnose <scenario>` drives it; the
  dashboard and eval suite will call the same function.
- **Grounding (S3), partial:** every remediation step must quote a runbook line;
  we hydrate the *full* top runbook (retrieval returns symptom-matching chunks,
  often not the Remediation section) and check each quote appears in it under a
  loose normalisation. This slice *flags* violations and marks a no-steps
  proposal as "escalate". The "regenerate once, then downgrade the whole
  proposal to escalate" enforcement is Week 2's guardrail layer.
- **Deferred to Week 2:** the approval gate + `pending_approval` table (S1), the
  Haiku guardrail second pass, redaction (S5), Langfuse tracing, the triage
  router (this slice takes the alert text as given), the REST/SSE endpoint.
- Model: `claude-sonnet-5` for the loop (CLAUDE.md / SPEC pin), adaptive thinking.
- **Revisit trigger:** if the tool-runner leaves beta *and* our per-turn logic
  still fits its hook model (approval gate included), reconsider — a superseding
  ADR. Until both hold, the manual loop stays.
