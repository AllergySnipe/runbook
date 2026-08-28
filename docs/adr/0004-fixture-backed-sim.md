# ADR 0004 — The sim: a fixture-backed environment, not a real backend

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** Ritvik
- **Supersedes:** —

## Context

The "gather signal" step of the loop (`SPEC.md`) needs somewhere to gather signal
*from*: metrics, logs, deploy history, service dependencies for `paymentsvc`.
`SPEC.md` non-goals are explicit — *"No real infrastructure integration. The sim
is the world."* — so the question is not *whether* to fake it but *how*.

Constraints:

1. **Deterministic.** Evals and CI must get identical tool outputs on every run.
2. **Offline, no credentials** (the ADR-0002 value — same reason embeddings are local).
3. **Authored signal.** Each of the six modelled failure modes has a runbook whose
   Diagnosis section claims "you will see X." The sim is where X is made true, so a
   later eval can check whether the agent reads X and reaches that runbook's
   conclusion — and *not* a neighbouring runbook's.
4. **Cheap to author and review.** Six scenarios (plus a healthy baseline) × four
   signal types is a lot of surface; hand-typing raw data points is untenable.

## Options considered

### A. Stand up real backends in a test harness (Prometheus + Loki + a fake deploy API)

- **For:** highest fidelity; exercises real query languages.
- **Against:** heavy, slow, flaky in CI; needs seed data anyway; PromQL/LogQL
  surface area the agent doesn't need. Directly contradicts the `SPEC.md` non-goal.

### B. Replay a public dataset (Loghub, LO2, RCA100 / OpenTelemetry-Demo captures)

- **For:** realistic log *texture*; no authoring.
- **Against:** wrong domain — Loghub is supercomputers/Hadoop; none emit payments
  lines like `pool timeout: no connection available after 5000ms`. The signal
  lines a runbook greps for must be hand-written regardless. Real datasets are
  large research bundles with timestamp-remapping cost and varied licences.

### C. Hand-authored fixtures + a compact spec expander (chosen)

- Each scenario is a directory of small YAML/JSONL files: a manifest (`service`,
  anchor `T+0`, incident window, the alert that fires, the runbook it targets),
  a list of **compact metric specs** (`baseline` + `segments` of `step`/`ramp`
  transitions, optional `sawtooth`), hand-written **signal log lines**, a deploy
  history, and a dependency graph. The sim expands specs into deterministic
  time-series at query time (jitter seeded from `(series, timestamp)`, so a
  point's value is identical regardless of the query window).
- **Noise** (`sim/noise.py`): a payments-domain INFO/WARN line generator, seeded
  per scenario, interleaved with the signal lines so `search_logs` faces a real
  haystack. This is the deliberate replacement for a public log dataset — see B.
- **For:** deterministic; offline; every scenario file is small and reviewable in
  a diff; the signal is authored to match exactly one runbook; the linkage tests
  (`tests/test_scenario_runbook_linkage.py`) run each runbook's Diagnosis section
  against its scenario and assert it lands.
- **Against:** the fixtures are our own fiction — realism is only as good as the
  authoring; the noise generator's vocabulary is finite. Adding a scenario is
  manual work.

## Decision

**Option C.** The sim is fixture-backed and in-process. It never touches Postgres
(it is static test data, like the synthetic runbooks in `corpus/`, not persistent
state) and never reads the wall clock.

## Consequences

- `src/runbook/sim/` — `clock.py` (relative-time `T±…` parsing), `series.py`
  (spec → series + summary), `noise.py`, `logs.py`, `infra.py`, `scenario.py`.
- `src/runbook/tools.py` — the four read-only tools (`query_metrics`,
  `search_logs`, `get_recent_deploys`, `get_service_dependencies`) over a loaded
  scenario, with structured returns and a `TOOLS` allowlist (`SPEC.md` S2
  groundwork). All read-only: state-changing actions live in the runbooks but are
  gated behind human approval (Week 2).
- `runbook sim <action> <scenario> …` — a manual inspection CLI (not part of the
  product loop).
- Wheel packaging: hatchling includes the fixture files (verified in the built wheel).
- **Revisit trigger:** if realistic captured logs become worth the cost — for the
  Week 3 log-injection red-team, or if the noise generator's finite vocabulary
  starts to bias eval results — revisit **OpenTelemetry Demo** (Apache-2.0,
  microservice e-commerce with fault injection) as a noise source, behind a
  `logs.jsonl` + capture-file merge, and write a superseding ADR.
