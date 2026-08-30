# ADR 0016 — The flywheel: real traces → regression coverage

- **Status:** Accepted
- **Date:** 2026-08-31
- **Deciders:** Ritvik

## Context

Week 3's plan: *"Flywheel: failing eval/prod traces → new golden cases; human
corrections → incident memory."* The second half is ADR-0015. This ADR is the
first half — turning what actually happened in production (or in a red-team run)
into permanent regression coverage, so a bug that's fixed today can't quietly
come back.

Two feedback sources, and they are **not** the same kind of test:

1. A **prod incident** where the loop's proposal was checked by a human
   (`runbook outcome`). This is a *diagnosis-quality* signal — "would the loop
   get this right?" — the same shape as the golden set (`evals/cases.py`).
2. A **red-team attack** that is blocked on the hardened path. This is a *safety*
   signal — "does the injection defence still hold?" — scored by
   `redteam/detect.py` (signal taxonomy), not by the eval judge.

`runbook eval` already has `--bless` (freeze scores from a prior run). There was
no equivalent for *adding* a case, and no scheduled guard for the red-team.

## Decision

### 1. `runbook promote <run_id>` — prod incident → golden `EvalCase` stub

`evals/promote.render_case_stub` renders a paste-ready `EvalCase(...)` from a
`RunRecord` + its recorded `OutcomeRecord`: alert and scenario filled from the
run; every **label** (`expect_triage`, `expect_runbook`, `expect_failure_mode`,
`expect_disposition`, `reference_root_cause`) emitted with a `# TODO confirm`
and seeded from what the run produced — except `reference_root_cause`, which
comes from the **human-confirmed outcome**, not the model's guess.

It prints to stdout. It does **not** append to `cases.py`. `cases.py` is
explicit that a wrong label is worse than no eval — it punishes a correct answer
and rewards a wrong one. So the human pastes the stub into the right list,
checks each label against the scenario fixture and runbook, and commits. The
tool removes the transcription friction; it does not remove the human.

`promote` refuses a run with no recorded outcome (`--force` overrides, and the
stub then screams that `reference_root_cause` is the model's unverified guess).
This makes the intended path **outcome → promote**: the same human confirmation
that feeds incident memory (ADR-0015) also seeds the eval label. One act of
review, two durable artifacts.

### 2. Red-team attacks stay a separate suite, triggered by the change

The full `redteam/attacks.py` list already **is** the regression set — `runbook
redteam` exits non-zero on any hardened-condition success or errored case. What
was missing is a trigger. It's kept out of `ci.yml` (real model + retrieval
calls, needs secrets — ADR-0012 §4), so `.github/workflows/redteam.yml` runs
`runbook redteam --condition hardened` on:

- **`pull_request`** touching a defence surface (`prompts/**`, `core/loop.py`,
  `core/guardrail.py`, `core/triage.py`, `rag/**`, `redteam/**`) — the trigger
  that actually reopens a hole is a change to one of these, and running on the PR
  **blocks** the regression instead of reporting it after merge.
- **`schedule`** weekly — a cheap backstop for drift that never touches those
  files: a dependency/model bump, a `config.py` model swap, the served model
  changing under a pinned `:free` name.
- **`workflow_dispatch`** — on demand.

An incident happening is *not* a trigger — the defences don't change because
someone got paged.

A promoted attack does **not** become an `EvalCase`. A poisoned-log case has
different inputs (an injected surface), a different success definition (a
`detect.py` signal, not a judge score), and a different bar (ASR = 0, not "≥
threshold"). Folding it into `cases.py` would blur "the golden set is what a
competent responder concludes". New attacks are added to `attacks.py` directly,
with a `control/*` peer where disposition manipulation is in scope.

## Alternatives considered

- **`promote --append` writes into `cases.py` with skip-until-filled markers.**
  Rejected — a half-filled case in the file is an invitation to commit it
  unreviewed. stdout forces a conscious paste.
- **One unified "regression" command over both eval + red-team.** Rejected —
  different scorers, different bars, different CI story (one has no secrets, one
  needs them). A shared entry point would hide that.
- **Run the red-team after every real incident run.** Rejected — the defences
  don't change per incident, so this would re-run an expensive (~15–25 real loop
  runs, 429-prone) suite for no new signal, and burn the rate limit that live
  runs need.
- **A nightly `schedule` only.** Rejected in favour of the PR trigger: nightly
  reports a regression up to 24h *after* the change that caused it, and burns CI
  every day even when nothing relevant changed. The PR trigger catches it at the
  right moment; the weekly cron keeps the out-of-path safety net.
- **Run the red-team in `ci.yml`.** Rejected — `ci.yml` is deliberately
  secret-free and deterministic (ADR-0008/0012); mixing in real model calls
  breaks that contract for every push.

## Consequences

- New CLI `runbook promote`; new `evals/promote.py` + `render_case_stub` export.
- New `.github/workflows/redteam.yml` (PR-on-defence-surface + weekly + manual) —
  needs `OPENROUTER_API_KEY`, `JINA_API_KEY`, `DATABASE_URL`,
  `DATABASE_URL_UNPOOLED` repo secrets.
- `docs/BACKLOG.md` "Red-team → eval flywheel" item closed;
  `docs/security/log-injection.md` §5 re-run note points at the workflow.
- **Revisit if:** promoted cases accumulate enough that they want their own list
  + a "promoted from" provenance field on `EvalCase`; or the red-team's free-tier
  flakiness (429s → errored cases → red job) needs a retry/quarantine lane
  distinct from a real regression.
