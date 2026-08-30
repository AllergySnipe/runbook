// Shared editorial content — used across the Overview, How-it-works and the
// tool pages so there's one source of truth for the project's own story.

export const TAGLINE = "An on-call incident-response copilot that does the first fifteen minutes.";

export const PROBLEM = [
  "On-call engineers lose 15–20 minutes per incident to orientation, not repair: finding the right runbook, recalling whether this has happened before, assembling context from dashboards, logs, deploy history and wikis. For most incidents, mean-time-to-resolution is dominated by that lookup cost.",
  "Runbook takes an alert and does that orientation work automatically — it triages, retrieves the relevant runbook and similar past incidents, gathers signal through read-only tools, and proposes a diagnosis with an ordered remediation, every step grounded in a real runbook line. It pauses for a human before anything that changes system state.",
];

// The loop — SPEC §"What it does". Order matters; keys are used for anchors.
export const LOOP_STEPS = [
  {
    key: "triage",
    n: 1,
    title: "Triage",
    short: "Sort the alert into a lane",
    body: "A cheap prompted classifier reads the raw alert (Alertmanager JSON or free text) and picks one of four lanes: known-runbook, novel incident, noise-or-flapping, need-more-info. Noise and need-info short-circuit here — no loop is spent. Recall on real incidents is prioritised over precision: a false 'noise' is far worse than a false 'investigate'.",
    safety: null,
  },
  {
    key: "retrieve",
    n: 2,
    title: "Retrieve",
    short: "Find the runbook + similar incidents",
    body: "Hybrid search over a corpus of ~2,100 runbook and postmortem chunks: dense vector similarity and Postgres full-text, fused with Reciprocal Rank Fusion, then a cross-encoder rerank of the top 30 into a top-k. The full top runbook is hydrated from disk so the Remediation section is in context, not just the symptom chunk that matched. A separate lookup also pulls back any past incident whose root cause a human has confirmed, when the new alert closely matches it — as context, never a grounding source.",
    safety: null,
  },
  {
    key: "investigate",
    n: 3,
    title: "Investigate",
    short: "Gather signal with read-only tools",
    body: "A manual tool-use loop: the model asks for a tool, the code runs it against the simulated environment and feeds the result back, repeat — capped at 8 rounds. The four tools (metrics, logs, recent deploys, service dependencies) only observe. A call outside the allowlist is refused and logged.",
    safety: "S2",
  },
  {
    key: "synthesize",
    n: 4,
    title: "Synthesise",
    short: "Draft a grounded diagnosis",
    body: "The model produces a structured diagnosis — root cause, confidence, evidence, and ordered remediation steps — as validated JSON. Every remediation step must quote a verbatim line from the runbook. Steps that don't are regenerated once; still-ungrounded steps are dropped; a proposal with nothing left becomes an escalation.",
    safety: "S3",
  },
  {
    key: "guardrail",
    n: 5,
    title: "Guardrail",
    short: "Classify every action, independently",
    body: "For each surviving step the guardrail decides read-only vs state-changing — using the runbook's own tags, a high-precision mutation-verb scan, and a fail-safe to state-changing — not trusting the model's self-label. A cheap second-model pass can only tighten the result. The run gets a disposition: auto, needs-approval, or escalate.",
    safety: "S1",
  },
  {
    key: "approve",
    n: 6,
    title: "Approve",
    short: "Pause for a human on state changes",
    body: "A state-changing step is written to Postgres as a pending approval; the run stays 'awaiting-approval' until a human resolves every one, from the dashboard or the CLI. The only code that writes an approval is the human-initiated command — the loop has no path to it. Read-only proposals resolve automatically.",
    safety: "S1",
  },
  {
    key: "record",
    n: 7,
    title: "Record",
    short: "Write the audit row",
    body: "Every run produces one row: what triggered it, what was retrieved, every tool call and its result, the proposal, the guardrail verdict, token usage, and what a human approved. This row is the audit record — and, after a human corrects the root cause, the seed for a new eval case.",
    safety: "S6",
  },
];

export const SAFETY = [
  {
    id: "S1",
    title: "No state change without recorded human approval",
    body: "The agent can never execute a state-changing action without a pending-approval row resolved by a human. Enforced structurally: the only writer of an 'approved' state is the human-initiated command.",
    status: "enforced",
  },
  {
    id: "S2",
    title: "Tool allowlist",
    body: "The agent can only call tools on a fixed allowlist. Anything else is refused and logged.",
    status: "enforced",
  },
  {
    id: "S3",
    title: "Grounded proposals only",
    body: "Every remediation step must cite a specific retrieved runbook line. Ungrounded proposals are regenerated once, then downgraded to an escalation.",
    status: "enforced",
  },
  {
    id: "S4",
    title: "Retrieved + tool content is untrusted data",
    body: "Corpus text and tool output — especially log lines — go into prompts inside clearly delimited, labelled blocks, never as instructions.",
    status: "enforced",
  },
  {
    id: "S5",
    title: "Secret / PII redaction",
    body: "A deterministic scrub removes secrets and PII from any text before it reaches a model provider or a trace — at two enforcement points: tool output and retrieved runbook text.",
    status: "enforced",
  },
  {
    id: "S6",
    title: "Every run produces an audit record",
    body: "Trigger, retrieval, tool calls, proposal, approvals — all persisted as one row per run.",
    status: "enforced",
  },
];

export const STACK = [
  ["Python 3.12 · uv", "Backend + CLI, one lockfile."],
  ["FastAPI", "REST + SSE for run progress; serves the built SPA."],
  ["Postgres + pgvector (Neon)", "Corpus index, incident runs, approvals, eval results."],
  ["Provider-neutral model layer", "One call site; per-role model routing with fallback chains."],
  ["Jina (hosted retrieval)", "Embeddings + cross-encoder reranking over one API — no model in the image."],
  ["React + Vite + Tailwind", "This dashboard; built to static files, served by FastAPI."],
  ["Docker → Render", "One image, git-push-to-deploy."],
];

export const NON_GOALS = [
  "No real infrastructure — the sim is the world. No Prometheus, Kubernetes or cloud APIs.",
  "No auto-remediation without human approval. Ever — not even for actions that look safe.",
  "No multi-tenancy and no auth in v1 — a single shared instance.",
  "No Slack / chat integration. The dashboard is the UI.",
];
