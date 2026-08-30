-- 0012_langfuse_trace.sql — link an incident run to its Langfuse trace (ADR-0017).
--
-- Tracing (ADR-0017) records one Langfuse trace per `diagnose()` run — the
-- per-run drill-down (model calls, tokens, latency waterfall) that the audit
-- record (S6) and the eval set don't give.
--
--   langfuse_trace_id   the 32-char W3C trace id — canonical, for `langfuse-cli`
--                       lookups and future online-scoring linkage
--   langfuse_trace_url  the ready-to-open dashboard link — the "trace ↗" the
--                       IncidentDetail page renders (best-effort; may be NULL if
--                       the project-URL lookup failed even though the id is set)
--
-- Both nullable, no default: NULL means tracing was off for that run (every row
-- before this slice, plus any run made with `LANGFUSE_ENABLED=false` / no keys).

alter table incident_runs add column langfuse_trace_id  text;
alter table incident_runs add column langfuse_trace_url text;
