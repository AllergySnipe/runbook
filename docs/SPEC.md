# Runbook — Product & Technical Spec

Status: **draft, under review**. Owner: Ritvik. Last updated: 2026-08-27.

This is the contract for v1. If a change contradicts this doc, the doc gets updated first, in
its own commit, with the reasoning.

---

## Problem

On-call engineers lose 15–20 minutes per incident to *orientation*, not fixing: finding the
right runbook, recalling similar past incidents, assembling context from dashboards, logs, and
wikis. Mean-time-to-resolution is dominated by this lookup cost, not by the actual repair.

## Who it's for

On-call software engineers at a company that has: a set of named services, written runbooks, a
history of postmortems, and a Prometheus Alertmanager–style alerting system. **v1 assumes a
single team / single tenant.**

## What it does (the loop)

1. Receives an alert (Alertmanager JSON) or a free-text incident report — via the CLI or the
   dashboard.
2. **Triages** it: known-runbook / novel incident / noise-or-flapping / need-more-info.
3. **Retrieves** the most relevant runbook + similar past postmortems.
4. **Gathers signal** via read-only tools: metrics, logs, recent deploys, service dependencies.
5. **Proposes** a diagnosis + ordered remediation steps, each grounded in a retrieved runbook
   step.
6. **Gates actions**: any state-changing step pauses the run as a pending approval; a human
   approves or rejects it in the dashboard (or at a CLI prompt). Read-only steps run
   automatically. Steps outside an allowlist are refused.
7. **Learns**: after resolution the human records the actual root cause; that correction
   becomes a new eval case and is stored as incident memory.

## In scope (v1)

- **CLI** exposing the core loop as a command (primary interface, built first).
- **Web dashboard**: the FastAPI app exposes a REST + SSE API; a Vite/React SPA (built to
  static files, served by the same FastAPI app) is the UI — incident list, run timeline
  (retrieved context + tool calls + proposal), approve/reject action, post-resolution
  root-cause form. **No Slack.**
- RAG over a corpus of public runbooks + postmortems + ~6 synthetic runbooks for the toy
  service (see Toy service).
- A simulated environment (`sim/`) serving metrics / logs / deploys from fixtures — **no real
  infrastructure**.
- Triage router, retrieval (hybrid search + rerank), agentic tool loop, guardrail layer,
  approval gate.
- Incident memory: append-only timeline + similar-incident retrieval.
- Eval suite (golden scenarios + scorers) wired into CI.
- Langfuse tracing + online scoring on sampled runs.
- Secret/PII redaction before any model call; audit log.
- Cost/latency tracking (`$/incident`, p50/p95 time-to-first-suggestion).
- Deployed to Render from day one, redeployed on every merge to `main`.

## Toy service

The synthetic runbooks and the sim center on **`paymentsvc`**, a payments API:

- **Dependencies:** Postgres (primary store), Redis (idempotency keys + rate limiting), a
  `payments-events` queue (async webhooks/ledger updates), an external `acquirer-gw` (card
  processor).
- **Neighbouring services:** `checkout-web`, `ledger`, `notification-svc`, `fraud-scoring`.
- **Modelled failure modes (one runbook each):** DB connection-pool exhaustion → p99 latency;
  `acquirer-gw` timeouts → elevated 5xx; `payments-events` consumer lag → delayed webhooks;
  Redis eviction → idempotency failures / double-charge risk; a bad migration locking a table
  after a deploy; noisy-neighbour CPU throttling.

## Non-goals (v1) — explicit

- **No real infrastructure integration.** No real Prometheus / Kubernetes / cloud APIs. The
  sim is the world.
- **No auto-remediation without human approval. Ever** — not even for actions that look safe,
  if they're outside the read-only allowlist.
- **No multi-tenant / multi-team support, and no auth in v1.** A single shared instance is
  sufficient for this scope; auth and multi-tenancy are covered in the "productionize"
  write-up rather than built here.
- **No Slack / chat-channel integration.** The dashboard is the UI.
- **No voice / vision / multimodal.**
- **No fine-tuning in the core build** — it's a week-4 stretch, behind a flag, optional.
- **No on-call scheduling, paging, or escalation-policy management** — that's PagerDuty's job.
- **Not a general chatbot** — off-topic requests are declined.

## Safety requirements

| # | Requirement |
|---|---|
| S1 | The agent can never execute a state-changing action without a recorded human approval (a `pending_approval` row resolved by a human via dashboard or CLI). |
| S2 | The agent can only call tools on an allowlist; anything else is refused and logged. |
| S3 | Every remediation step in a proposal must cite a specific retrieved runbook step. Ungrounded proposals are regenerated once, then downgraded to "escalate to human". |
| S4 | Content from the corpus or from tool output (**especially logs**) is treated as untrusted data, never as instructions. |
| S5 | Secrets and PII are redacted from any text before it reaches a model provider or a trace. |
| S6 | Every run produces an audit record: what triggered it, what was retrieved, what tools were called, what was proposed, what was approved. |

## How we'll know it works (eval criteria)

- **Retrieval** — correct runbook in top-k for a labeled scenario. Target: hit@3 ≥ 0.85 on the
  golden set.
- **Triage** — category matches the label. Target: ≥ 0.90 accuracy; recall on "real incident"
  prioritised over precision.
- **Diagnosis** — LLM-judge score ≥ threshold vs. a reference root cause, plus exact-match on
  category.
- **Action safety (hard, must be 100%)** — no golden scenario ever yields a state-changing
  action without an approval step; no out-of-allowlist tool call.
- **Groundedness (hard)** — every proposed step maps to a real runbook step, or the proposal
  is an escalation.
- **Regression** — no eval metric drops between commits without a written justification.

## Data sources

- **Runbooks:** `Scoutflo/Scoutflo-SRE-Playbooks`, `techlearn-center/incident-response-runbooks`,
  Kubernetes / AWS troubleshooting docs, + a few synthetic runbooks for a toy service.
- **Postmortems:** the public ones linked from `danluu/post-mortems`.
- **Logs / eval seeds:** Loghub (BGL, Thunderbird, HDFS — some with alert labels).
- **Structured incident metadata:** `thecentrabyteinc/raw-data`.
- **Fine-tuning (week 4):** Loghub alert labels + Sonnet-labelled synthetic Alertmanager
  payloads.

## Architecture (one paragraph)

A FastAPI app (REST + SSE for run progress, `/health`) on Render (Docker, `$PORT`), also
serving the built React SPA as static files. Postgres (Neon) holds the pgvector index, incident memory,
pending approvals, audit log, and eval results. A thin custom orchestration layer — **no agent
framework** — runs: redact → triage (Haiku) → retrieve (pgvector hybrid + rerank) → tool loop
against `sim/` → diagnose (Sonnet) → guardrail validation (Haiku second pass) → pause for
approval → record. The CLI and the dashboard both drive this same orchestration function.
Langfuse wraps every model and tool call for tracing; a sample is online-scored. The eval
suite runs this same orchestration code path in CI against golden scenarios.

## Glossary

- **Runbook** — a written procedure for handling a known failure mode.
- **Postmortem** — a retrospective writeup of a past incident.
- **Grounding** — the property that a generated claim or step traces to specific retrieved
  source text.
- **Triage** — classifying an incoming alert to choose the handling path.
- **The sim** — the fixture-backed fake environment standing in for real infrastructure.
