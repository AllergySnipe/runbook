-- 0013_online_scores.sql — online scoring: grade a sample of real runs (ADR-0018).
--
-- Offline evals (`runbook eval`) grade the loop against a fixed golden set with
-- known-correct answers, before a change ships. This table holds the other half
-- (SPEC "a sample is online-scored"): automatic scores computed for REAL
-- production runs, where there is no label. Only reference-free scorers run here
-- — invariant re-checks (S1-S3) and properties of the output itself
-- (grounding coverage, retrieval confidence, disposition) — never anything that
-- needs to know the right answer.
--
-- The scores are also pushed to the run's Langfuse trace (`create_score`, keyed
-- on `incident_runs.langfuse_trace_id`) for the quality-over-time view; this
-- table is the local mirror so `runbook scores` and the flywheel
-- (`runbook promote`) work without Langfuse access.
--
-- Upsert on (run_id, name), NOT append-only: a run has one CURRENT score per
-- metric. Re-scoring a run (e.g. after a scorer change) replaces the value —
-- unlike `incident_memory`, where a correction is a new historical row.

create table online_scores (
    id          bigint generated always as identity primary key,
    run_id      text not null references incident_runs (id) on delete cascade,
    name        text not null,            -- 'safety-invariants' | 'grounding-coverage' | ...
    value_num   double precision,         -- NUMERIC / BOOLEAN (1.0 / 0.0) scores
    value_text  text,                     -- CATEGORICAL scores (e.g. disposition)
    data_type   text not null,            -- 'NUMERIC' | 'BOOLEAN' | 'CATEGORICAL'
    comment     text,                     -- why (which invariant broke, coverage fraction, ...)
    created_at  timestamptz not null default now(),
    unique (run_id, name)
);

create index online_scores_name_created_at_idx
    on online_scores (name, created_at desc);
