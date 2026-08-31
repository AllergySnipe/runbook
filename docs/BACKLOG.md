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

- ~~**`/security` dashboard page**~~ — done: `GET /api/redteam` serves the tracked
  `src/runbook/redteam/latest.json` snapshot (`redteam-results/` is gitignored → not in the
  image, so `runbook redteam --condition both --bless` freezes a blessed run, parallel to
  `evals/baseline.json`); `web/src/routes/Security.jsx` renders ASR by surface + by goal
  (baseline vs hardened), the attacks that got through + what contained each, the defence
  stack, and the residual risks. Narrative sourced from `docs/security/log-injection.md`
  (still canonical) via `web/src/content/security.js`.

- ~~**Online scoring on sampled runs**~~ — done (ADR-0018, migration 0013):
  `core/scoring.py` grades a sampled fraction of real runs with reference-free scorers
  (`safety-invariants` / `grounding-coverage` / `retrieval-confidence` / `disposition`) after
  `record_run()` in the CLI + web paths; scores → `online_scores` + the Langfuse trace;
  `runbook scores --low` is the prod→eval on-ramp. **Deferred:** the reference-free
  plausibility LLM judge (needs calibration — ADR-0018 §2) and a `GET /api/scores` dashboard
  panel (ADR-0018 §7).

- **Poisoned-doc hydration hardening** — `core/loop.py::_full_doc` hydrates the full source
  for the top retrieved chunk when it has an on-disk `path`. A retrieved doc with no path
  falls back to its chunk text, which is the vector by which a poisoned corpus document
  becomes the "primary runbook" (red-team `doc/*` cases). Options: only ever treat
  corpus-jailed synthetic runbooks as hydration-eligible; or sign the synthetic corpus at
  ingest and check the signature here. Tracked from ADR-0012's residual-risk note.

- **Red-team → eval flywheel** — the prod→eval half is done (ADR-0016): `runbook promote
  <run_id>` renders a golden `EvalCase` stub from a real incident run, seeded from the
  human-confirmed `runbook outcome` (labels marked TODO — the human reviews + commits). The
  red-team half is **closed as "measured manually, not gated"**: a CI gate was built (a
  `redteam/baseline.json` of accepted residuals + `runbook redteam --gate` + a workflow) and
  removed — a single hardened run has no statistical power on free-tier models (dispositions
  swing `auto`↔`needs-approval` run-to-run), and a reliable K≈3-run gate isn't affordable on
  a free tier. Red-team stays a point-in-time tool, diffed against `redteam-results/` by hand.
  Revisit on a paid model tier.
