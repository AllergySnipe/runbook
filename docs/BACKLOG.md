# Backlog — deferred items

Things we've deliberately decided to do *later*, so they don't clog the current slice.

- **Keep-warm ping** — a ~3-line GitHub Action on a cron (every ~10 min during the day) that
  hits the deployed `/health` endpoint so the host doesn't idle the service to sleep
  (~1 min cold start otherwise). Add once deploy is live and the cold start is actually
  annoying.

- **`/security` dashboard page** — surface the red-team ASR table (baseline vs hardened) and
  the attack families on the console, alongside `/evals`. The data is in
  `redteam-results/*.json` + `docs/security/log-injection.md`; needs a small API endpoint
  and a route. Deferred out of the Week 3 slice-2 harness build (ADR-0012).

- **Poisoned-doc hydration hardening** — `core/loop.py::_full_doc` hydrates the full source
  for the top retrieved chunk when it has an on-disk `path`. A retrieved doc with no path
  falls back to its chunk text, which is the vector by which a poisoned corpus document
  becomes the "primary runbook" (red-team `doc/*` cases). Options: only ever treat
  corpus-jailed synthetic runbooks as hydration-eligible; or sign the synthetic corpus at
  ingest and check the signature here. Tracked from ADR-0012's residual-risk note.

- **Red-team → eval flywheel** — a successful `runbook redteam` attack should be promotable
  into a golden regression case (Week 3 flywheel item). Manual for now.
