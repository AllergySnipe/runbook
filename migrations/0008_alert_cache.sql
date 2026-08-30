-- 0008_alert_cache.sql — the semantic cache for the incident-loop prefix (ADR-0014).
--
-- On-call alerts are bursty and repetitive: the same page fires many times during
-- one incident with drifting text (current metric value, timestamps). Redoing
-- triage + hybrid retrieval for each near-duplicate is waste. This table stores an
-- embedding of each proceeding alert plus the cheap prefix it produced — the
-- triage verdict and the retrieved runbook set. A later alert within
-- `cache_similarity_threshold` cosine and `cache_ttl_s` seconds reuses them.
--
-- Only the *prefix* is cached, never the diagnosis: the environment moves between
-- two fires of the same alert, and an approval-gated system must not serve last
-- hour's remediation for this hour's incident. See ADR-0014.
--
-- Same vector(1024) space + cosine ops as `documents` (migration 0007) — the
-- embedding is `jina.embed(..., task="retrieval.query")` of the raw alert, the
-- identical vector the retrieval vector-leg uses (folded: computed once per run).

create table alert_cache (
    id          bigint generated always as identity primary key,
    alert_norm  text not null,                    -- normalised alert text — human-readable key, not used for matching
    embedding   vector(1024) not null,            -- match key: cosine vs incoming alert
    triage      jsonb not null,                   -- the cached TriageResult
    retrieved   jsonb not null,                   -- the cached RetrievedChunk list (serialised)
    run_id      text references incident_runs (id) on delete set null,  -- which run populated this (debugging)
    created_at  timestamptz not null default now()
);

create index alert_cache_embedding_idx
    on alert_cache using hnsw (embedding vector_cosine_ops);
create index alert_cache_created_at_idx
    on alert_cache (created_at desc);
