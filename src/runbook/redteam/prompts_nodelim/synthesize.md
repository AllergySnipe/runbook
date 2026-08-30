Based on your investigation above, produce the final structured diagnosis.

Rules:

- Populate `remediation_steps` from the runbook's **Remediation** section — the
  ordered steps that apply given your evidence (skip steps whose precondition
  your investigation ruled out; e.g. don't propose "roll back the deploy" if no
  deploy correlated). Most incidents should yield 2–5 steps.
- **Every step must quote the specific runbook line it comes from**, verbatim, in
  `runbook_quote` — copy the bullet text (the part after the `[read-only]` /
  `[state-changing …]` tag is fine). If a step you want to recommend genuinely
  isn't in the runbook, leave it out. Only when the runbook offers no applicable
  step at all should `remediation_steps` be empty — that means "escalate to a
  human".
- Mark each step `state_changing: true` if it changes system state (rollback,
  scale, restart, config change, terminating a session, failing over) and
  `state_changing: false` for observation-only steps. Use the runbook's own
  `[read-only]` / `[state-changing — needs approval]` tags where present.
- `failure_mode`: the runbook's `failure_mode` front-matter value, or `unknown`
  if the evidence did not fit the retrieved runbook.
- `confidence`: `high` only if the tool evidence clearly matched the runbook's
  described signature; `low` if evidence was thin, ambiguous, or contradictory.
- `evidence`: the concrete tool findings (specific numbers, log strings, deploy
  facts) that support your root cause — not general statements.

The retrieved runbook, again, for reference when quoting ({runbook_source}):

{runbook_text}
