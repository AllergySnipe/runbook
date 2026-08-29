-- 0004_incident_runs.sql — the audit record (SPEC S6) + the approval gate (S1).
--
-- One `incident_runs` row per `diagnose()` call: what triggered it, what was
-- retrieved, what tools ran, what was proposed, and the guardrail's verdict.
-- This row IS the audit record. When the guardrail disposition is
-- `needs-approval`, one `pending_approvals` row is written per state-changing
-- remediation step; the run stays `awaiting-approval` until a human resolves
-- every one of them (via `runbook approve|reject`, later the dashboard).
--
-- No code path in the loop can write an approval in any state but `pending` —
-- the transition to `approved` happens only in `resolve_approvals()`, called
-- only by a human-initiated command. That is S1, enforced structurally.

create table incident_runs (
    id            text primary key,          -- app-generated, e.g. 'run_a1b2c3d4'
    alert         text not null,
    scenario      text not null,

    triage_category   text not null,
    triage_rationale  text not null,
    triage_confidence text not null,

    disposition   text,                      -- 'auto'|'needs-approval'|'escalate'; null if triage short-circuited
    status        text not null,             -- 'short-circuited'|'awaiting-approval'|'resolved'|'rejected'|'escalated'

    diagnosis     jsonb,                     -- the full structured proposal (null if short-circuited)
    retrieved     jsonb not null default '[]'::jsonb,   -- [{title, path, source, score}]
    tool_calls    jsonb not null default '[]'::jsonb,   -- [{name, input, is_error}]
    guardrail     jsonb,                     -- verdicts + second-pass concerns + regenerate/drop

    usage         jsonb not null default '{}'::jsonb,
    iterations    integer not null default 0,
    hit_max_iters boolean not null default false,
    elapsed_s     numeric not null default 0,

    created_at    timestamptz not null default now(),
    resolved_at   timestamptz
);

create index incident_runs_status_idx     on incident_runs (status);
create index incident_runs_created_at_idx on incident_runs (created_at desc);
create index incident_runs_scenario_idx   on incident_runs (scenario);

create table pending_approvals (
    id               bigint generated always as identity primary key,
    run_id           text not null references incident_runs (id) on delete cascade,
    step_index       integer not null,
    action           text not null,
    runbook_quote    text not null,
    classifier_reason text not null,

    state        text not null default 'pending',   -- 'pending'|'approved'|'rejected'
    resolved_by  text,
    resolved_at  timestamptz,
    note         text,

    unique (run_id, step_index)
);

create index pending_approvals_run_id_idx on pending_approvals (run_id);
