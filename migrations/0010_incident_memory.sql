-- 0010_incident_memory.sql — incident memory: the flywheel's episodic store (ADR-0015).
--
-- SPEC step 7 ("Learns"): once a run reaches a terminal state a human records
-- what ACTUALLY turned out to be the root cause. That confirmed outcome is
-- embedded here and retrieved on future similar alerts as *context* — "here is
-- how a similar page resolved last time" — never as a grounding source (S3 still
-- requires every remediation step to quote a runbook line).
--
-- Append-only. A correction is a new row, never an UPDATE: incident_runs (the
-- model's proposal) and this table (the human's confirmation) together show
-- proposed-vs-actual over time. Only human-confirmed outcomes land here — that is
-- the guard against feedback poisoning, where the model's own guess would
-- otherwise silently become "memory" and be retrieved to reinforce itself.
--
-- Same vector(1024) space + cosine ops as `documents` (0007) and `alert_cache`
-- (0008): the embedding is jina task=retrieval.query of the run's alert text, the
-- identical vector the retrieval + cache legs use (computed once per run).

create table incident_memory (
    id                   bigint generated always as identity primary key,
    run_id               text not null references incident_runs (id) on delete cascade,
    alert                text not null,
    scenario             text not null,
    embedding            vector(1024) not null,
    actual_root_cause    text not null,          -- the human's confirmed RCA
    actual_failure_mode  text,                   -- optional: the runbook failure_mode it matched
    model_root_cause     text,                   -- what diagnose() proposed (proposed-vs-actual)
    model_was_correct    boolean,                -- the human's verdict on the proposal
    created_by           text not null,
    created_at           timestamptz not null default now(),
    unique (run_id)                              -- one recorded outcome per run
);

create index incident_memory_embedding_idx
    on incident_memory using hnsw (embedding vector_cosine_ops);
create index incident_memory_created_at_idx
    on incident_memory (created_at desc);
