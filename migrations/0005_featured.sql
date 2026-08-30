-- 0005_featured.sql — mark a small set of curated runs as "featured".
--
-- A reviewer hitting a cold instance shouldn't wait ~40s for their first rich
-- view. Featured runs are hand-picked exemplars (one per interesting ending —
-- resolved / escalated / rejected) surfaced first on the dashboard. Set via
-- `runbook feature <id>`; nothing in the loop writes this column.

alter table incident_runs add column featured boolean not null default false;

create index incident_runs_featured_idx on incident_runs (featured) where featured;
