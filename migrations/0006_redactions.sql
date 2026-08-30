-- 0006_redactions.sql — S5 audit: how many secrets / PII spans were scrubbed
-- from this run's tool output before it entered the message history and this
-- record (SPEC S5, ADR-0011).
--
-- Count only — never the values. The redactor runs deterministically in
-- `core/loop.py`; `llm.py` re-scrubs every outgoing message as the backstop.

alter table incident_runs add column redactions integer not null default 0;
