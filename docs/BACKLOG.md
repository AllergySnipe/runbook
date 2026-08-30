# Backlog — deferred items

Things we've deliberately decided to do *later*, so they don't clog the current slice.

- ~~**Keep-warm ping**~~ — done (ADR-0013): `.github/workflows/keepwarm.yml` crons `/health`
  every 10 min. GitHub cron is unreliable (late, pauses after 60d idle); add an external
  monitor (UptimeRobot / cron-job.org) if the cold start still bites.

- ~~**Persist the run row at *start*, not just on success**~~ — done (ADR-0014):
  `web_api.py::_run_incident` writes a `record_run_start` stub before the loop, and the
  `except` calls `mark_run_failed` (→ `status='failed'` + error text). `record_run` upserts
  over the stub. A crashed dashboard run no longer 404s.

- ~~**Cache the query embedding**~~ — done (ADR-0014): `diagnose()` computes the alert
  embedding once and passes it to both `cache.lookup` and `retrieve(query_vec=)`.

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
