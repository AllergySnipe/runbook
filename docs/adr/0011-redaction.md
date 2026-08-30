# ADR 0011 — Redaction: deterministic scrub, two enforcement points

- **Status:** Accepted
- **Date:** 2026-08-30
- **Deciders:** Ritvik
- **Supersedes:** —

## Context

`SPEC.md` S5: *secrets and PII are redacted from any text before it reaches a
model provider or a trace.* This is the last unenforced safety invariant (S1–S4
and S6 are in code + evals; S5 was "not started").

The exposure is cumulative, not dramatic. Every string the loop builds ends up
somewhere outside code we audit: the model provider (OpenRouter → an upstream
host → their subprocessors → their abuse-monitoring logs, retained ~30 days), a
future Langfuse trace (full prompts, months of retention, rendered in a UI people
screenshot), the `incident_runs` audit record (ours, but long-lived and rendered
publicly on `/incidents/:id`), and — Week 3's flywheel — failing prod traces
promoted into golden eval cases committed to a **public** repo. Any one of those
leaking a connection string is an incident.

Where secrets actually appear here: **tool output**, overwhelmingly. Logs are the
classic carrier — a stack trace printing a DSN, a debug line dumping
`Authorization: Bearer …`. The alert text is a lesser vector (hostnames, a token
in a URL). The corpus is committed and human-reviewed; in practice it carries
nothing (verified).

## Decision

### 1. Deterministic scrubber, no model pass

`src/runbook/redact.py` — regex + checksums. Detectors: emails, connection
strings (`scheme://user:pass@host`), `Authorization:` / `Bearer` tokens, JWTs,
vendor key prefixes (AWS `AKIA`, GitHub `ghp_`, Slack `xox[baprs]-`, OpenAI
`sk-`, GCP `AIza`, Stripe `[sr]k_live/test_`), `-----BEGIN … PRIVATE KEY-----`
blocks, `keyword=value` credentials, payment cards, private IPv4.

Everything here is **structural** — a prefix, a delimiter, a checksum, a keyword.
That is exactly what regex is good at, and it makes the scrubber `pytest`-able
(CLAUDE.md rule 6: deterministic code gets tests).

**Rejected: an NER / LLM pass.** It would catch free-form PII (names, addresses)
that regex cannot. But: (a) our real risk surface is entirely structured, so it
buys almost nothing here; (b) it makes redaction probabilistic and un-auditable —
"why did it miss this?" has no answer; (c) it costs a model call per redaction —
and the call ships the raw text to a provider *to decide whether it's safe to
ship to a provider*. The honest cost of this decision is **zero recall on
free-form PII**; acceptable for a synthetic-incident corpus, and it would be the
wrong call for, say, customer-support transcripts.

### 2. Two enforcement points (defence in depth)

- **`llm.py` — the choke point.** `_redact_outgoing` scrubs `system` + every
  string message `content` on every `complete` / `run_turn` / `parse` call. This
  is the *structural* S5 guarantee: exactly one place text leaves for a provider,
  and it redacts. Every callsite (triage, guardrail second pass, eval judge,
  synthesis) is covered without touching them.
- **`core/loop.py` — targeted.** Each tool result is scrubbed in
  `_tool_results_for` *before* it enters both the message history and the
  `ToolCall` sink that `store.py` serialises — so the audit record ("or a
  trace") is clean too, with an auditable count (`incident_runs.redactions`,
  migration `0006`) and a `redaction` timeline event.

Neither layer alone suffices: the choke point never touches the audit record; the
targeted layer misses the alert and every non-loop call.

### 3. Ground against post-redaction text

`diagnose()` scrubs the retrieved `runbook_text` once, then uses that same
scrubbed string for the prompt *and* `_check_grounding` (S3). The check must
verify the model's `runbook_quote` against exactly what the model saw — otherwise
a redaction inside a quoted line would fail grounding, regenerate, drop the step,
and turn a correct fix into an escalation. In practice a no-op for the synthetic
corpus; load-bearing the day a retrieved postmortem carries a private IP.

### 4. Two calibration choices worth recording

- **Luhn checksum on cards.** `\d{13,19}` alone matches trace IDs, byte counts,
  timestamps. Requiring the card checksum (a random number passes ~10% of the
  time, a real card 100%) turns "matches everything" into "matches cards".
- **RFC 1918 IPv4 only.** Public IPs are public — and the danluu postmortems are
  *about* `1.1.1.1`. The sensitive thing about an IP is internal network
  topology, which is precisely the private ranges.

## Consequences

- S5 is enforced structurally, deterministically, and tested
  (`tests/test_redact.py`: a positive fixture per kind; every synthetic runbook
  asserted byte-for-byte unchanged; idempotency; the Luhn and RFC-1918 gates).
- Redaction is **idempotent** — the `[redacted:*]` placeholders match no
  detector — so the choke point re-scrubbing what the loop already scrubbed is a
  no-op.
- **Precision is favoured on runbook text, recall on logs.** An over-redaction
  that corrupts a runbook line breaks grounding; a missed secret in a log is a
  breach. Patterns are anchored (prefix / keyword / checksum / delimiter), never
  "a long alphanumeric string", and the negative fixtures are real runbook prose.
- Free-form PII (names, physical addresses, spelled-out numbers) is **not**
  caught. If a future corpus needs it, the NER pass slots in as a third detector
  behind a flag — it does not change the architecture.
- Verified: 242 tests green; real eval on `db-connection-pool-exhaustion`
  (4 cases, OpenRouter) — all hard checks clear, groundedness included.
