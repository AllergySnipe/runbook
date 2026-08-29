# ADR 0007 — The approval gate: a persisted state machine, not a blocking call

- **Status:** Accepted
- **Date:** 2026-08-30
- **Deciders:** Ritvik

## Context

ADR-0006 built the classification that decides a remediation step is
state-changing. `SPEC.md` S1 then requires: *the agent can never execute a
state-changing action without a recorded human approval — a `pending_approval`
row resolved by a human.* S6 requires an audit record per run. This ADR settles
the shape of the gate.

The naive reading of "wait for human approval" is a **blocking call**:
`diagnose()` runs, reaches a state-changing step, and parks — the function (or
the HTTP request behind it) sits waiting until a human answers.

## Options considered

### A. Block the run until approval

- **For:** simplest control flow; the run object stays in memory with all its
  context.
- **Against:**
  - The human isn't there. Approval may come in seconds or hours, from a
    different person, via the dashboard. A parked thread/request for hours is a
    resource leak and a single-point-of-failure — one restart (Render redeploys
    on every push) and the pending decision is lost with no record of where the
    incident stood.
  - The Week-2 dashboard flow is inherently async: incident list → open a run →
    Approve. That is a *second, independent request against stored state*, not a
    callback into a still-running function. A blocking design can't serve it.
  - It hides failure. If the box dies mid-wait, what state is the incident in?
    Unknowable.

### B. Persisted state machine (chosen)

`diagnose()` runs to completion and returns its `DiagnoseResult` with a
`disposition` (`auto` / `needs-approval` / `escalate`). Persistence is a separate
step (`core/store.py::record_run`), called by the CLI / dashboard — **not** by
`diagnose()` itself, so the eval suite can run the loop without writing to prod.

`record_run` writes one `incident_runs` row (the audit record — trigger,
retrieved, tool calls, proposal, guardrail verdict) and, for `needs-approval`,
one `pending_approvals` row per state-changing step. The run's `status` is a
lifecycle field:

```
short-circuited   (triage bailed — terminal)
resolved          (auto, or every step approved — terminal)
escalated         (no grounded remediation — terminal)
awaiting-approval → resolved  (all approved)
                  → rejected  (any rejected — terminal)
```

`runbook approve|reject <id>` (later a dashboard endpoint) transitions the
approval rows and recomputes `status` in one transaction. Nothing blocks.

The lifecycle rule is a **pure function**, `compute_status(disposition,
approval_states)`, unit-tested exhaustively with no DB — that is where the S1
guarantee is actually pinned. The SQL is a thin shell with one
skipped-without-a-DB integration test.

- **For:** survives restarts; serves the async dashboard directly; failure state
  is always written down; S1 is a tested pure function, not a hope.
- **Against:** more moving parts than a blocking call; the run's rich in-memory
  context is flattened to JSON columns (acceptable — it's written once, read
  whole for audit/display).

## Decision

**Option B.** The gate is: a `needs-approval` run is not `resolved` until its
`pending_approvals` rows are all `approved`, and the only code that writes
`approved` is `resolve_approvals()`, reachable only from a human-initiated
command. The loop has no path to it — S1 enforced structurally.

Persistence lives in `core/store.py`, invoked by the CLI, never inside
`diagnose()`.

## Consequences

- The CLI `diagnose` command is non-interactive: it records the run and prints
  the `runbook approve|reject` commands. No `[y/N]` prompt (also avoids the
  interactive-input limitations of the harness). The dashboard will add the
  point-and-click path against the same `resolve_approvals`.
- `incident_runs` + `pending_approvals` satisfy S6 for now. A separate
  append-only `audit_events` log (every state transition, not just the final
  state) is deferred to the incident-memory / flywheel slice.
- Rejecting any single step rejects the whole run — a partially-applied
  remediation is worse than none.
- Nothing is executed in v1 regardless of approval (there are no state-changing
  tools; the sim is read-only). The gate records the decision; wiring approved
  steps to real actuators is out of scope for this build (`SPEC.md` non-goal).
