# ADR 0016 — The flywheel: real traces → regression coverage

- **Status:** Accepted
- **Date:** 2026-08-31
- **Deciders:** Ritvik

## Context

Week 3's plan: *"Flywheel: failing eval/prod traces → new golden cases; human
corrections → incident memory."* The second half is ADR-0015. This ADR is the
first half — turning what actually happened in a prod incident into permanent
regression coverage, so a bug that's fixed today can't quietly come back.

The obvious second source is a red-team run, but it turns out **not** to be the
same kind of test — a diagnosis-quality signal ("would the loop get this
right?", the golden set's shape) vs. a safety signal ("does the injection defence
hold?", scored by `redteam/detect.py` signals). And, as §2 works through, it
can't be gated reliably on this infra at all.

`runbook eval` already has `--bless` (freeze scores from a prior run). There was
no equivalent for *adding* a case.

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

### 2. The red-team stays a manual measurement — not a CI gate

The flywheel's other half was meant to be "a hardened red-team run that fails CI
on a regression". We built it — a `redteam/baseline.json` of accepted residuals,
a `runbook redteam --gate` that fails only on a `log`-surface success, a *new*
succeeding attack, or an accepted residual resolving less safely — and ran it.

It doesn't work on this infra, and the reason is instructive. Across three
hardened runs **with no code change between them**, an attack's disposition
swings `auto` ↔ `needs-approval` and a `log`-surface exfil goes 0/2 then 1/1. The
free-tier models (`glm-5.2` → `minimax` fallback chain) are non-deterministic
enough that **one sample per attack has no statistical power**. A single-run gate
either cries wolf every week or misses a real regression in the noise. Making it
reliable needs K≈3 runs per attack (≈3× the runtime and rate-limit budget) — not
worth it for a portfolio build on a free tier.

So the red-team reverts to what ADR-0012 §4 always said it was: a **point-in-time
measurement, run by hand** after a change to a defence surface (`prompts/*`,
`core/{loop,guardrail,triage}`, retrieval), with the report diffed against
`redteam-results/` and `docs/security/log-injection.md` §3 refreshed. The
`--bless`/`--gate` machinery and the `redteam.yml` workflow are removed; the
attack corpus, the `format_comparison` before/after table, and the deterministic
detector unit tests stay.

A promoted attack does **not** become an `EvalCase` regardless. A poisoned-log
case has different inputs (an injected surface), a different success definition (a
`detect.py` signal, not a judge score), and a different bar. Folding it into
`cases.py` would blur "the golden set is what a competent responder concludes".
New attacks are added to `attacks.py` directly, with a `control/*` peer where
disposition manipulation is in scope.

## Alternatives considered

- **`promote --append` writes into `cases.py` with skip-until-filled markers.**
  Rejected — a half-filled case in the file is an invitation to commit it
  unreviewed. stdout forces a conscious paste.
- **One unified "regression" command over both eval + red-team.** Rejected —
  different scorers, different bars, different CI story (one has no secrets, one
  needs them). A shared entry point would hide that.
- **Gate the red-team in CI (any of: "any hardened success", a blessed-baseline
  diff, a `--surface log` filter, a PR-path trigger, a nightly/weekly cron).**
  All built and tried; all rejected. A single hardened run has no statistical
  power on free-tier models (§2) — the "any success" form is red every run, and
  the baseline-diff form flagged a real-looking regression on its first run that
  could not be told apart from variance. Making it reliable needs K≈3 runs per
  attack, which the free tier can't afford. So: no CI gate.
- **Run the red-team after every real incident.** Rejected regardless — the
  defences don't change because someone got paged.

## Consequences

- New CLI `runbook promote`; new `evals/promote.py` + `render_case_stub` export.
  This is the whole of the delivered flywheel.
- The red-team is unchanged from ADR-0012: `runbook redteam`, run by hand, diffed
  against `redteam-results/`. No `--gate`, no `baseline.json`, no workflow.
- `docs/BACKLOG.md` "Red-team → eval flywheel" item: the promote half is done;
  the red-team half is closed as "measured manually, not gated" with the reason.
- **Revisit if:** promoted cases accumulate enough that they want their own list
  + a "promoted from" provenance field on `EvalCase`; or a paid model tier makes
  a K-run red-team gate affordable.
