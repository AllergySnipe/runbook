# ADR 0001 — No agent framework; thin custom orchestration

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** Ritvik
- **Supersedes:** —

## Context

Runbook needs an orchestration layer that runs, per incident:

```
redact → triage → retrieve (hybrid + rerank) → tool loop (read-only, against sim/)
       → diagnose → guardrail validation → pause for approval → record
```

This is the kind of workload agent frameworks (LangChain, LlamaIndex, CrewAI, LangGraph,
Haystack, …) exist to serve. We need to decide whether to adopt one or write the loop
ourselves.

Two properties of this system raise the stakes:

1. **The prompt and the context window are the product.** Retrieval quality, grounding, and
   injection resistance all depend on controlling exactly what text reaches the model — the
   layer frameworks abstract away.
2. **Safety is enforced in code, not prompts** (`SPEC.md` S1–S6). The approval gate and the
   tool allowlist must be provably un-bypassable, and easy to audit.

## Options considered

### A. Adopt a general framework (LangChain / LlamaIndex)

- **For:** fast start; prebuilt document loaders, splitters, retrievers, agent loops, memory
  classes; many vector-store and model-provider integrations; large body of examples.
- **Against:** the two things we most need to control — the *exact* prompt sent to the model
  and the *exact* context assembled — are the two things these frameworks abstract away.
  Debugging "why did the model propose that" means unwinding framework layers. API churn has
  historically been high, and a large transitive dependency tree inflates the image. Adds
  more concepts than our simple control flow removes.

### B. Adopt a graph/state-machine framework (LangGraph)

- **For:** a real state machine for agent control flow, built-in checkpointing, first-class
  human-in-the-loop interrupts — which maps well onto our approval gate.
- **Against:** still pulls the LangChain ecosystem for the surrounding pieces; the state-
  machine payoff only materialises when control flow is genuinely complex (concurrent
  branches, durable execution across restarts). Ours isn't, yet.

### C. Thin custom orchestration (chosen)

- Write the loop in explicit Python (~a few hundred lines). Use **focused libraries for
  narrow, stable jobs** — the Anthropic SDK (tool use + structured output), a Postgres/
  pgvector client, an embeddings/rerank call, the Langfuse SDK, `pytest` — but nothing that
  wants to own control flow.
- **For:** full control of prompt + context assembly; minimal dependencies and image size;
  safety-critical paths (approval, allowlist) are plain code we can read and test directly;
  the provider SDK now covers most of what a framework's agent loop used to provide.
- **Against:** we write and maintain the loop, retry logic, and state handling ourselves; no
  free integrations (swapping vector store or adding a provider is manual work); more code
  before the first working slice.

## Decision

**Option C — thin custom orchestration.** Frameworks that abstract prompt construction,
context assembly, or control flow are excluded. Narrow single-purpose libraries are fine and
expected.

## Consequences

- `core/` will contain an explicit, readable orchestration function that the CLI, the
  dashboard, and the eval suite all call. Estimated a few hundred lines.
- The approval gate is a `pending_approval` row + an explicit branch in the loop, not
  framework middleware — directly testable against `SPEC.md` S1.
- We accept manual effort to change infrastructure choices later; `SPEC.md` non-goals say we
  won't need to.
- **Revisit trigger:** if the control flow becomes a genuine state machine — concurrent
  investigation branches, or a need for durable execution / checkpointing across process
  restarts — reconsider **LangGraph specifically** (not a general framework), and write a
  superseding ADR.
