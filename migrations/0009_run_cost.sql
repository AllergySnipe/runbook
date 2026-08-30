-- 0009_run_cost.sql — per-incident cost estimate + cache-hit flag (ADR-0014).
--
-- `cost_usd` is what the run's token usage would cost at the models' paid list
-- prices (the free OpenRouter endpoints bill $0). Computed from the per-model
-- token breakdown now carried in `incident_runs.usage` ({"by_model": {...}}).
--
-- `cache_hit` records whether the semantic cache (migration 0008) served this
-- run's triage + retrieval prefix — feeds the cache-hit-rate stat on the
-- dashboard.
--
-- Both are additive with defaults; existing rows keep 0 / false.

alter table incident_runs add column cost_usd  numeric not null default 0;
alter table incident_runs add column cache_hit boolean not null default false;
