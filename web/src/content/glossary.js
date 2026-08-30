// Inline-glossary entries. Keyed by a short slug; each body is one or two plain
// sentences. Referenced from <Term term="slug" />. Keep these tight — the point
// is to let the prose stay lean while nothing stays opaque.

export const GLOSSARY = {
  triage: {
    title: "Triage",
    body: "Classifying an incoming alert to pick a handling path — before spending any real work on it. Runbook sorts alerts into four lanes: known-runbook, novel incident, noise-or-flapping, need-more-info.",
  },
  "novel-incident": {
    title: "Novel incident",
    body: "An alert that doesn't match any known runbook. Runbook still investigates, but tells the model the retrieved runbook is a weak prior and to weight live evidence more heavily.",
  },
  grounding: {
    title: "Grounding (S3)",
    body: "The property that every remediation step traces to a specific line in a retrieved runbook. Ungrounded steps are regenerated once, then dropped; a proposal with nothing left becomes an escalation.",
  },
  disposition: {
    title: "Disposition",
    body: "The loop's verdict on what should happen with a proposal: auto (read-only steps, safe to run), needs-approval (has a state-changing step), or escalate (no grounded fix — hand to a human).",
  },
  "hybrid-search": {
    title: "Hybrid retrieval",
    body: "Running two searches — dense vector similarity and keyword full-text — and fusing their rankings, so both semantic matches and exact identifier matches surface.",
  },
  rrf: {
    title: "Reciprocal Rank Fusion",
    body: "A parameter-free way to combine two ranked lists: each item scores 1/(k + rank) in each list, and the sums are re-sorted. Rewards items ranked high by either retriever.",
  },
  "cross-encoder": {
    title: "Cross-encoder rerank",
    body: "A second, slower model that scores each candidate against the query jointly (not as separate embeddings), used to re-order the top ~30 hybrid hits into a sharper top-k.",
  },
  "hit-at-3": {
    title: "hit@3",
    body: "The fraction of labelled scenarios whose correct runbook appears in the top 3 retrieved results. Runbook's target is ≥ 0.85; the golden set currently scores 1.00.",
  },
  pgvector: {
    title: "pgvector / HNSW",
    body: "A Postgres extension for storing embedding vectors and doing nearest-neighbour search, with an HNSW graph index for speed.",
  },
  embedding: {
    title: "Embedding",
    body: "A fixed-length vector of numbers that positions a piece of text in a semantic space, so 'connection pool exhausted' and 'ran out of DB connections' land near each other.",
  },
  "tool-loop": {
    title: "Tool-use loop",
    body: "The model is given a set of functions it can call. It asks for one, the code runs it and feeds the result back, and this repeats until the model stops asking — here, capped at 8 rounds.",
  },
  "read-only-tools": {
    title: "Read-only tools (S2)",
    body: "The four tools the agent can call — query_metrics, search_logs, get_recent_deploys, get_service_dependencies — only observe the environment. Any call outside this allowlist is refused and logged.",
  },
  "action-classification": {
    title: "Action classification",
    body: "The guardrail decides read-only vs state-changing for each remediation step independently of what the model claimed — using the runbook's own tags, a mutation-verb scan, and a fail-safe to state-changing.",
  },
  "second-pass": {
    title: "Second-pass review",
    body: "A cheap separate model call over the finished proposal that can only tighten it — upgrade a step to state-changing, flag one as unsupported — never loosen it.",
  },
  "approval-gate": {
    title: "Approval gate (S1)",
    body: "A state-changing step is written to the database as a pending approval; the run stays 'awaiting-approval' until a human resolves every one. The loop has no code path that can approve.",
  },
  "state-machine": {
    title: "Persisted state machine",
    body: "The approval gate isn't a function that blocks waiting for a human — it's rows in Postgres. compute_status() is a pure function mapping (disposition, approval states) → run status, unit-tested exhaustively.",
  },
  "audit-record": {
    title: "Audit record (S6)",
    body: "Every run writes one row capturing what triggered it, what was retrieved, every tool call, the proposal, the guardrail verdict, and what a human approved.",
  },
  "llm-judge": {
    title: "LLM-as-judge",
    body: "Using a model to score another model's output against a reference answer. Runbook's judge enumerates missing and hallucinated points before scoring, and runs a different model family than the one being judged.",
  },
  "golden-set": {
    title: "Golden eval set",
    body: "30 hand-labelled cases (6 scenarios × canonical + 3 paraphrases, plus negatives and novel alerts), each with the expected triage lane, runbook, failure mode and disposition.",
  },
  "hard-check": {
    title: "Hard check",
    body: "A pass/fail assertion that must be 100%: no golden case ever yields a state-changing step classified read-only, no out-of-allowlist tool call, no ungrounded step in a non-escalation.",
  },
  "regression-gate": {
    title: "Regression gate",
    body: "The eval compares each run to a blessed baseline.json. A metric dropping more than 0.05 below baseline and below target fails the run — no silent quality erosion between commits.",
  },
  sse: {
    title: "Server-Sent Events",
    body: "One long-lived HTTP response the server keeps writing to. The browser's EventSource parses each frame and auto-reconnects. One-way, text, plain HTTP — the right fit for streaming run progress.",
  },
  "no-job-queue": {
    title: "No job queue",
    body: "A run is a fire-and-forget asyncio task in the web process, tracked in memory; the finished audit record goes to Postgres. A restart loses in-flight runs — an accepted trade for a single-instance demo.",
  },
  "no-framework": {
    title: "No agent framework",
    body: "No LangChain / LlamaIndex / CrewAI. The loop is ~200 lines of explicit Python, because the loop is exactly where the safety branches live and a framework's tool-runner would hide them.",
  },
  sim: {
    title: "The sim",
    body: "A fixture-backed fake environment standing in for real infrastructure — deterministic metrics, hand-written signal logs plus generated noise, a deploy history and a dependency graph, per scenario.",
  },
  paymentsvc: {
    title: "paymentsvc",
    body: "The toy service everything centres on: a payments API backed by Postgres, Redis (idempotency + rate limiting), an events queue, and an external card-processor gateway.",
  },
  "idempotency-key": {
    title: "Idempotency key",
    body: "A client-supplied token that lets a payment request be retried safely — the server records the key and returns the original result instead of charging twice. Stored in Redis here.",
  },
  alertmanager: {
    title: "Alertmanager",
    body: "The Prometheus component that deduplicates and routes alerts. Its webhook payload (labels, annotations, a firing/resolved status) is one of the two input shapes Runbook accepts.",
  },
  "failure-mode": {
    title: "Failure mode",
    body: "A named, documented way the service breaks — each with its own runbook. Runbook models six: DB pool exhaustion, gateway timeouts, consumer lag, Redis eviction, bad-migration lock, CPU throttling.",
  },
  mttr: {
    title: "MTTR",
    body: "Mean time to resolution — the average wall-clock time from alert to fixed. For most incidents it's dominated by orientation (finding the runbook, recalling context), not the repair itself.",
  },
  redaction: {
    title: "Redaction (S5)",
    body: "Stripping secrets and PII from any text before it reaches a model provider or a trace. Specified for Runbook; not yet built.",
  },
  "incident-memory": {
    title: "Incident memory",
    body: "This system's own past incidents, each with the root cause a human confirmed after resolution. Retrieved as context on future similar alerts — 'how a page like this turned out last time' — but never as a grounding source. Only human-confirmed outcomes are stored, so the loop can't reinforce its own mistakes.",
  },
};
