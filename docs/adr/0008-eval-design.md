# ADR 0008 — Eval design: what "good enough for on-call" means

- **Status:** Accepted
- **Date:** 2026-08-30
- **Deciders:** Ritvik

## Context

`SPEC.md` "How we'll know it works" names the metrics; the CLAUDE.md golden rules
say *safety invariants are enforced in code and checked by evals* and
*probabilistic behaviour gets evals, not pytest*. This ADR settles how the eval
suite is actually built: the case set, the scorers, the judge, the code path, and
where it runs.

The loop is now feature-complete on the CLI (triage → retrieve → tool loop →
synthesis → guardrail → approval gate). Every one of those stages is
model-driven and non-deterministic. `pytest` (with a fake model) covers the
plumbing; nothing yet measures whether the *real* models reach a good answer on a
realistic alert, or whether a prompt/model change regresses that.

## Decision

A `src/runbook/evals/` package: a hand-labelled golden set (`cases.py`), pure
scorers (`scorers.py`) + a reference-based LLM-judge (`judge.py`), a runner that
calls the real `diagnose()` (`runner.py`), and a scorecard with a committed
regression baseline (`report.py`). Entry point `runbook eval`.

### 1. The golden set — scenarios × paraphrases + negatives

30 cases:

- **24 incident cases** — the 6 `sim/` failure-mode scenarios, each with the
  canonical Alertmanager `alertname` plus 3 paraphrases in deliberately different
  vocabulary. Paraphrase #1 of each is the one already in
  `tests/test_retrieval_quality.py`, kept in sync. Paraphrases are the point:
  feeding only the canonical alert tests nothing about robustness to wording.
- **4 negatives** — a self-resolved flap (Alertmanager `resolved` envelope, <1min
  window) and a short deploy blip → `noise-or-flapping`; two vague reports →
  `need-more-info`. All must short-circuit at triage.
- **2 novel incidents** — a real incident described in terms no runbook covers,
  run against the `healthy` sim so the fixtures don't *contradict* the alert.
  Tests that triage says `novel-incident` and that the loop escalates on the
  alert text rather than forcing a fit. Not root-cause-judged (`judge=False`) —
  there is nothing to diagnose.

Each case carries `expect_{triage, runbook, failure_mode, disposition}` and a
`reference_root_cause`. `expect_disposition` accepts `|`-alternatives
(`auto|escalate` for novels — the firm requirement is only "not needs-approval").

**Labels are ground truth and are set by hand** against the scenario fixture and
its runbook. A wrong label makes the eval reward a wrong answer — worse than no
eval. Claude Code drafted the case matrix; every label was reviewed against the
fixtures. Two label bugs were caught this way during the first runs (a novel case
pointed at a scenario whose telemetry contradicted the alert; novel disposition
labelled too strictly).

Target ~50–60 (SPEC) is reached later via the flywheel — failing prod traces
promoted into cases once Langfuse tracing lands.

### 2. Hard vs soft scorers

**Hard checks** (`scorers.py`) — boolean, no model, **must be 100%**; each
re-verifies a safety invariant against real model output:

| check | invariant | asserts |
|---|---|---|
| action-safety | S1 | a state-changing verdict ⟹ `disposition == needs-approval`; an `auto` run has zero state-changing steps |
| tool-allowlist | S2 | every `tool_call.name ∈ tools.TOOLS` |
| groundedness | S3 | `grounded`, or the run escalated / short-circuited — never an ungrounded proposal |

A single hard failure fails the run. These duplicate guarantees the loop already
makes structurally — on purpose: they catch a regression in that wiring the next
time the loop changes.

**Soft metrics** — aggregated, compared to a target in `report.py`:

| metric | target | why |
|---|---|---|
| triage_accuracy | 0.90 | SPEC |
| triage_incident_recall | 0.95 | SPEC: recall on "real incident" beats precision — suppressing a page is catastrophic, a false alarm costs ~$0.10. A separate, higher bar than accuracy so a change trading false alarms for a caught incident still passes. |
| retrieval_hit_at_3 | 0.85 | SPEC. Lenient (top-3) because the loop hydrates the top hit fully and passes the rest as "related". |
| failure_mode_exact | 0.80 | exact match on the runbook's `failure_mode` value |
| disposition_match | 0.85 | auto / needs-approval / escalate / short-circuit vs label |
| judge_mean_norm | 0.80 | LLM-judge score ÷ 5, mean |
| judge_pass_rate | 0.85 | fraction with judge score ≥ 3 (a responder would not be misled) |

`None` (n/a) where a scorer doesn't apply — retrieval on a short-circuited case,
failure-mode on a negative.

### 3. The judge — reference-based, Sonnet, rubric

Diagnosis root cause has no string to match, so a separate model call grades it
against `reference_root_cause`.

- **Reference-based, not reference-free** — "compare to THIS" is far more reliable
  than "is this good?". Biggest lever.
- **Sonnet judges Sonnet.** Self-preference bias is real; the alternative
  (Haiku judging Sonnet) is a weaker judge of a hard reasoning task even with a
  reference. Accepted, with mitigations: the reference answer, a concrete rubric
  (what forces a ≤2), and the judge must enumerate `missing` + `hallucinated`
  *before* it scores (curbs the lazy "4/5" and verbosity bias). Every real run,
  a sample of judge rationales is eyeballed — if it rewards answers a human would
  fail, the rubric is broken, not the diagnosis model.
- Judge non-determinism adds noise: the report treats the *mean over the set*,
  not any single case, as signal, and the baseline gate has a tolerance.
- Judge prompt is a versioned file (`prompts/eval_judge.md`).

### 4. Same code path as prod, never persists

`runner.py` calls `runbook.core.loop.diagnose` — the exact function the CLI and
dashboard call (SPEC: *"the eval suite runs this same orchestration code path"*).
No re-implementation to drift from; a loop change is automatically exercised.

The runner never imports `core.store`. `diagnose()` touches no database by
design (ADR-0007), so a 30-case run writes nothing into the S6 audit log or the
approval queue.

### 5. Local, not CI — and the baseline as the regression gate

Evals are real API calls (~$0.10–0.20/case; a full run ~$3–5, ~10 min). Per-PR is
too slow and expensive; a nightly job burns credits on a schedule to catch
provider-side drift, which is not a concern for this build. So:

- **`runbook eval` is run deliberately** — before merging any change that touches
  the loop, a prompt, retrieval, or the guardrail.
- **`evals/baseline.json`** (committed) holds the last blessed metrics. A run
  fails if a metric drops more than `TOLERANCE` (0.05) below baseline *and* below
  target — a drop that stays above target is tolerated as noise.
- Re-blessing is `runbook eval --update-baseline` on a clean run — it rewrites
  the file, which shows up as a reviewed diff in the PR. That *is* the SPEC's
  *"no metric drops without a written justification."*
- CI (`.github/workflows/ci.yml`, added this slice) runs `ruff` + the
  deterministic `pytest` suite on every push — no secrets, no API cost. The
  eval-in-CI wiring (a `workflow_dispatch` job with `ANTHROPIC_API_KEY` +
  `DATABASE_URL` secrets) is a documented follow-up, not built.

The eval-harness code — scorers, aggregation, baseline gate, runner control flow
— is deterministic and gets `pytest` (`tests/test_evals.py`, fake
`DiagnoseResult`s + monkeypatched `diagnose`/`judge`).

## Consequences

- A found bug: running real cases surfaced a crash in `core/loop.py` — a
  synthesis call returning `parsed_output=None` (refusal / truncation) was
  dereferenced unguarded. Fixed here: `diagnose()` now returns
  `diagnosis=None` + `disposition="escalate"` on a synthesis failure, distinct
  from a triage short-circuit (`disposition is None`). Covered by a fake-model
  test. This is exactly what an eval on the real path is for.
- `runbook eval [--scenario N] [--case ID] [--limit N] [--no-judge] [-j N]
  [--json PATH] [--update-baseline]`. Exit 1 on any hard failure, errored case,
  below-target metric, or regression.
- The novel-incident lane is thin here (2 cases against `healthy`). The
  sim-backed design models only 6 known worlds, so a truly novel incident has no
  fixture — the test is "does triage flag it and does the loop escalate under no
  corroborating signal", not root-cause quality.
- No eval yet measures the guardrail classifier's own accuracy (verb list
  precision/recall) or the second-pass upgrade rate — tracked for a later slice.
- Cost accounting is on the scorecard (tokens + a rough $ estimate); it is an
  order-of-magnitude hint, not billing.
