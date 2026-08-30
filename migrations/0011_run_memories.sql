-- 0011_run_memories.sql — record which past incidents the loop was shown (ADR-0015).
--
-- Incident memory (0010) retrieves similar confirmed incidents and puts them in
-- the diagnosis prompt as context. The audit record (S6) must capture that — "what
-- was retrieved" now includes memory, not just corpus chunks — so a reviewer can
-- see exactly what steered a proposal.
--
-- Additive with a default; existing rows keep '[]'.

alter table incident_runs
    add column memories jsonb not null default '[]'::jsonb;
