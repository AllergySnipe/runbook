# ADR 0018 — Online scoring: grade a sample of real runs

- **Status:** Accepted
- **Date:** 2026-09-01
- **Deciders:** Ritvik

## Context

ADR-0017 shipped Langfuse tracing and deferred the other half of the SPEC
commitment — *"Langfuse wraps every model and tool call for tracing; **a sample
is online-scored**"* — with the `obs.score()` stub as the seam. This ADR fills it.

The gap it closes: `runbook eval` grades the loop against 24 hand-labelled cases
*before a change ships* — a lab measurement, controlled inputs, known-correct
answers. Nothing grades the loop on **real traffic**. A regression that the
golden set doesn't happen to cover, a retrieval corpus that drifts, a provider
model that quietly gets worse — none of that shows up until someone reads a
specific trace.

The hard constraint that shapes everything here: **a real incident has no
label.** An alert firing through the dashboard has no `expect_triage`, no
`reference_root_cause`. So every *reference-based* metric (`triage_accuracy`,
`retrieval_hit_at_3`, `failure_mode_exact`, the reference judge) is simply
unavailable online. Online scoring can only use scorers that judge a **property
of the output itself** or **re-verify an invariant** — never "did it match the
right answer".

## Decision

### 1. Reference-free scorers only — and they're the safety-critical ones

`src/runbook/core/scoring.py`, pure functions over a `DiagnoseResult`:

| Score | Type | What it measures | Skipped when |
|---|---|---|---|
| `safety-invariants` | BOOLEAN | S1 (approval gate) + S2 (tool allowlist) + S3 (grounding) **all still hold** on this real output; `comment` names any breach | never |
| `grounding-coverage` | NUMERIC | fraction of remediation steps citing a real runbook line | short-circuit / no proposal |
| `retrieval-confidence` | NUMERIC | rerank score of the top retrieved chunk (Jina reranker, 0–1), RRF as fallback | no retrieval (short-circuit) or scores not preserved (cache hit) |
| `disposition` | CATEGORICAL | the outcome lane — not a quality metric; lets the others be sliced and the escalation rate be watched | never |

`safety-invariants` is the point. It re-runs exactly the checks the eval suite's
hard checks run (`evals/scorers.py::_HARD_CHECKS`), but on live traffic:
*"across the last N real incidents, did we **ever** auto-approve a state-changing
action, call an off-allowlist tool, or ship an ungrounded step?"* If that number
is ever below 1.0 on prod, it's an incident, and no label was needed to catch it.

The two S1–S3 implementations are deliberately **not shared** — `core/scoring.py`
needs a boolean + a short comment, `evals/scorers.py` needs a rich `HardFinding`
for the scorecard, and the checks are near-one-liners against existing
`DiagnoseResult` / `GuardrailReport` properties (`.grounded`, `.escalate`,
`guardrail.any_state_changing`). `tests/test_scoring.py::test_consistent_with_eval_hard_checks`
pins them together so they can't drift.

### 2. Not the LLM judge (yet)

A *reference-free* judge — "given the alert and the evidence gathered, is this
root cause supported? does it name a concrete subsystem? any contradiction?" —
would catch confident nonsense the deterministic scorers pass. It's deferred:

- It costs a model call per scored run (hence a real need for the sampling knob).
- Per standard eval practice, an LLM judge isn't trustworthy until it's
  **calibrated** against a hand-labelled set (build ~15 plausible/not-plausible
  diagnoses, run the judge, check the confusion matrix). That's its own task.
- The deterministic scorers are the actual safety signal; the judge is a
  quality nicety on top.

See *Revisit if*.

### 3. A sample rate, separate from the tracing rate

`scoring_sample_rate` (default `1.0`), independent of `langfuse_sample_rate`.
The economics differ: tracing is a background export thread (cheap, trace
everything); scoring is a DB write now and a judge call later (you may want to
trace 100% and score 20%). `1.0` for now — traffic is a demo — but the knob
exists so "how does this scale?" has a real answer (same reasoning as ADR-0017
§5). `scoring_enabled` is the kill-switch on top.

### 4. Where it runs — and where it must not

After `record_run()` (needs the persisted run + its `langfuse_trace_id`), in
**two call sites only**: the CLI `diagnose` command and the web app's
`_run_incident` — mirroring `obs.setup()`. The eval and red-team runners never
score, exactly as they never trace / cache / consult memory — a scored lab run
would pollute the prod quality dashboard.

Best-effort throughout: `score_and_record` catches and logs every failure,
telemetry never breaks or delays a run. In the web path it runs **after** the
`finished` SSE event so a slow write can't stall the stream.

### 5. Two sinks: Langfuse + Postgres

- **Langfuse** — `create_score(name, value, trace_id=…, data_type=…)` against the
  run's trace. This is *why* online scoring is worth doing: Langfuse then gives
  score-over-time charts, "filter traces where `grounding-coverage < 0.8`", score
  distributions — the quality-over-time view, for free.
- **Postgres** (`online_scores`, migration 0013) — because the Langfuse
  dashboard sits behind a project login and isn't portfolio-visible (ADR-0017
  §6), and because `runbook` commands and the flywheel need the scores locally.
  Upsert on `(run_id, name)` — a run has one *current* score per metric; a
  re-score replaces it (unlike `incident_memory`, where a correction is a new
  historical row).

### 6. The flywheel on-ramp — `runbook scores --low`

ADR-0016 turns a *human-reviewed* incident into a golden `EvalCase` stub
(`runbook promote`). Online scoring adds the trigger: `runbook scores --low`
lists recently-scored runs, flags the ones that tripped a threshold
(`safety-invariants < 1`, `grounding-coverage < 0.8`, `retrieval-confidence <
0.3`), and prints the `runbook outcome … && runbook promote …` on-ramp for each.
A human skims it: *"these real incidents scored low on retrieval-confidence —
worth adding to the eval set."* Surfacing only, never auto-promote — same
discipline as ADR-0016 (a wrong label is worse than no label).

### 7. No dashboard surface

`runbook scores` + `runbook run <id>` show the scores in the terminal; Langfuse
has the charts. A React panel was considered and dropped for this slice — the
scores are visible where they're acted on, and the portfolio-visible artifact
stays the console's run-anatomy view (ADR-0017 §6). Easy to add later off
`GET /api/scores`.

## Consequences

- One new module (`core/scoring.py`), one additive table (`online_scores`, 0013,
  applied to prod ahead of the deploy), no schema-version or event-type change.
- `obs.score()` gained `data_type=` and a `str` value (for CATEGORICAL); it's now
  a real call site, not a stub.
- `core/store.py` gained `record_online_scores` / `get_scores` /
  `list_recent_scores` + a `ScoreRecord`. `get_scores` is best-effort (missing
  table ⇒ "no scores"), so the code is safe if it runs against a DB without 0013.
- `_cmd_diagnose` restructured so scoring happens *before* `obs.flush()` — the
  old `finally: obs.flush()` ran before `_render_diagnosis` persisted anything.
- New tiny failure surface: a slow `create_score` or DB write after a run. All
  wrapped; worst case a run has a trace but no scores.

## Revisit if

- **A reference-free plausibility judge is wanted** — build + calibrate it
  (`references/judge-calibration.md`), gate it behind `scoring_sample_rate`
  (it's the expensive scorer), score name `diagnosis-plausibility`.
- **A Langfuse-native evaluator fits better** — Langfuse can run an LLM-judge
  server-side on a trace filter. If the judge lands, that may be the cleaner home
  than an in-process call.
- **`retrieval-confidence` needs a threshold, not a raw number** — calibrate what
  rerank score actually predicts a retrieval miss (parallel to the cache /
  memory calibration scripts) and score a boolean instead.
- **A dashboard panel** — `GET /api/scores` (aggregate: "over the last N real
  runs, safety invariants held 100%, mean grounding coverage 0.94") + a strip on
  `/evals`. Portfolio-visible where Langfuse isn't.
- **Cache hits lose `retrieval-confidence`** — the cached `RetrievedChunk`s don't
  carry rerank scores. If that blind spot matters, persist the top score on the
  cache row.
