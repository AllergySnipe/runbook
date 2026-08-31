# Is Runbook good enough to put in front of on-call?

Runbook proposes a diagnosis and a set of remediation steps during an incident. Before an
on-call engineer relies on it, someone has to decide whether it is good enough. This document
is that decision, the evidence behind it, and the parts the evidence does not cover.

## The recommendation

Run Runbook in advisory mode, with a hard approval gate on any state-changing step. That is
the mode the system is built for, and the evidence supports it.

Do not run it in auto-remediation mode, where it acts without a human. The evidence does not
support that yet. The gap is the size and realism of the test set, not the code.

## What "good enough" means here

"Good enough" has to be a set of thresholds, not a feeling. Runbook has four.

**Hard checks — 100%, every run.** Three boolean checks, each tied to a safety requirement in
the spec: no state-changing step ever reaches a responder without an approval step (S1); no
tool call outside the allowlist (S2); every remediation step in a non-escalation quotes a real
runbook line (S3). They use no model. One failure fails the release. A wrong action is a
different kind of event from a weak explanation, so it is not averaged into a score — it is a
gate.

**Soft metrics — above threshold, with a tolerance band.** Triage accuracy ≥ 0.90. Recall on
real incidents ≥ 0.95, set higher than accuracy because routing a real incident to "noise" is
the expensive mistake. Retrieval hit@3 ≥ 0.85. Failure-mode match ≥ 0.80. Disposition match ≥
0.85. LLM-judge score against a reference root cause ≥ 0.80 mean and ≥ 0.85 pass rate.

**Security — 0% attack success on the log surface**, and the approval gate never bypassed in
any condition. The log surface is the realistic one: an attacker who can get a string into a
log line, not one who can edit the prompt.

**Regression — no metric drops more than 0.05 below its blessed value and below target**
without a re-bless. The blessed values live in a committed file; lowering one is a reviewed
change, not a silent drift.

## The evidence today

Blessed baseline, 30 cases — 24 canonical-plus-paraphrased alerts across 6 failure modes, 4
healthy alerts that should be dismissed, 2 incidents no runbook covers:

| Metric | Value | Target |
|---|---|---|
| triage accuracy | 1.00 | 0.90 |
| triage incident recall | 1.00 | 0.95 |
| retrieval hit@3 | 1.00 | 0.85 |
| failure-mode exact | 1.00 | 0.80 |
| disposition match | 1.00 | 0.85 |
| judge mean (0–1) | 0.91 | 0.80 |
| judge pass rate | 0.96 | 0.85 |

Hard checks: clear. Red-team: the log surface held at 0% attack success, and the approval gate
was never bypassed in any condition.

The live numbers are on the [eval report page](https://runbook-cgkn.onrender.com/eval-report)
and the mechanics are on the [evals page](https://runbook-cgkn.onrender.com/evals).

## What the evidence does not cover

This is the part that matters.

**The golden set is small and built by one person.** Thirty cases. Twenty-four are paraphrases
of six underlying failure scenarios. A hit@3 of 1.00 on thirty cases means no miss was
observed. It does not mean misses are rare. The confidence interval is wide.

**The cases are close to the system's own distribution.** They use the same six scenarios the
simulated environment serves and the same corpus the system retrieves from. Real on-call
traffic will include failure modes no runbook covers, incidents with more than one cause, and
alerts worded by people and systems the set never saw. The evals show the system works on the
cases it was designed against. They do not show it generalizes.

**The judge is itself unvalidated.** Diagnosis quality has no string to match against, so a
separate model call grades it against a hand-written reference answer. The judge sees that
answer, which makes it lenient. There is no human-versus-judge agreement number yet. The
report leans on the pass rate, which is steadier than the mean, and treats the set average
rather than any single case as signal. That is a mitigation, not a validation.

**Cost and latency are not measured.** The instrumentation exists — cost per incident on every
run, p50/p95 on the stats endpoint. But the current model endpoints are capacity-constrained
enough that measured latency reflects queueing rather than the system's own work. These
numbers become meaningful on dedicated capacity.

**There is no production track record.** Online scoring is wired: a sample of real runs is
graded by the reference-free checks — the safety invariants, grounding coverage, retrieval
confidence — and the scores land on the run's trace. But there is no history of real incidents
to review yet.

## Why advisory-plus-gate is the right mode

The approval gate is a code property, not a prompt instruction. Any step classified
state-changing forces the run into "awaiting approval," and nothing executes regardless of the
disposition. The eval's hard check and the red-team both confirm it held. This is a claim the
evidence is strong enough to make, because it is checked deterministically rather than being a
statement about model quality.

Advisory output fails safe. The worst case is a wrong suggestion that a responder reads and
discards. The groundedness check and the judge metric bound how wrong it can be.

Auto-remediation would move the model from judgment-adjacent work to judgment-critical work.
The test set is too small and too close to the design distribution to support that move.

## What would change the recommendation

A path exists, and the infrastructure for it is built.

1. **A larger, more diverse golden set** — past ~150 cases, with real incident variety. The
   flywheel is the mechanism: `runbook scores --low` surfaces a weak real run, `runbook
   promote` turns it into a labeled case for review.
2. **A human-versus-judge agreement study** on a sample, tracked over time.
3. **Several weeks of shadow operation** — Runbook running alongside real incidents, with
   responder agreement recorded and online scores stable.
4. **Cost and latency measured on real capacity.**

Only then is it worth discussing auto-remediation, and only for the narrowest,
highest-confidence known-runbook path, behind a flag, A/B tested in the eval suite.

## How this stays honest

The same eval definitions run in more than one place. The full suite runs in CI on every
change. The reference-free subset runs on sampled production traffic, using the same logic,
pinned to the eval implementation by a test. The regression baseline is a committed file. The
red-team is a manual point-in-time run, repeated on any change to the prompts, the guardrails,
or retrieval.

## Bottom line

Runbook is good enough to help an on-call engineer work faster, with a human approving every
action. It is not good enough to act on its own. The reason is the test set, not the system —
and the parts that close that gap, the flywheel and the online scoring and the regression
gate, are the parts that are already built.

---

Related: [ADR-0008](../adr/0008-eval-design.md) (eval design), [ADR-0018](../adr/0018-online-scoring.md)
(online scoring), [SPEC](../SPEC.md) "How we'll know it works", [security report](../security/log-injection.md).
