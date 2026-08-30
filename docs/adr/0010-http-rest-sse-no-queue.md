# ADR 0010 — Exposing the loop over HTTP: REST + SSE, no job queue

- **Status:** Accepted
- **Date:** 2026-08-30
- **Deciders:** Ritvik

## Context

The incident loop (`core/`) has only ever been driven by the CLI. SPEC requires a
web dashboard: an incident list, a run timeline (retrieved context + tool calls +
proposal), the approve/reject action, a post-resolution root-cause field — served
by the same FastAPI app as a Vite/React SPA. This ADR covers the three decisions
that shape how the loop reaches the browser.

## Decision 1 — SSE for run progress, not WebSocket or polling

A `diagnose()` run takes 30–60s. The UI should narrate it (triage → retrieved →
each tool call → synthesis → guardrail → disposition), not spin.

- **Polling** (`GET /incidents/{id}` on a timer) — trivial and robust, but the
  step-by-step timeline feels laggy at any sane interval and most responses are
  "nothing changed". Kept anyway for the *list* view (4s poll) where coarse
  freshness is all that's needed.
- **WebSocket** — full duplex, but the client never streams *to* the server here
  (start / approve / reject are discrete POSTs). It would add a second protocol
  and a hand-rolled reconnect for capabilities we don't use.
- **SSE (chosen)** — one long-lived HTTP GET, server writes `event:`/`data:`
  frames as milestones happen. One-way, text, plain HTTP, browser `EventSource`
  auto-reconnects. Exactly the shape of "server narrates, client watches".

`GET /api/incidents/{id}/events` replays the buffered events, then streams live
ones until a terminal `finished` / `error` event, then closes. A 15s keepalive
comment keeps idle proxies from dropping it.

**Revisit if:** the UI grows a genuine client→server streaming need (live
collaboration on a run, a chat with the copilot) → WebSocket.

## Decision 2 — Background runs via `asyncio.create_task`, no job queue

`POST /api/incidents` must return an id immediately (the client then opens the
SSE stream) while the loop runs for the next minute.

The production answer is a task queue (Celery / RQ / Arq + Redis) with a separate
worker pool. We don't use one:

- **One instance.** Render free tier, single container — nothing to distribute to.
- **It's a demo.** A run that dies mid-flight on a redeploy is a shrug. The
  durable part — the finished audit record — is a Postgres row (SPEC S6)
  regardless. Only *in-flight* runs are ephemeral.
- **Thin orchestration** (ADR-0001). Redis + Celery + a worker process is exactly
  the machinery this project avoids.
- The loop is already `async` — the event loop runs it concurrently with serving
  other requests, in-process, for free.

`POST /api/incidents` picks an id, registers an in-memory `IncidentRun`, and does
`asyncio.create_task(_run_incident(...))`. Not FastAPI `BackgroundTasks` (those
are tied to the request that spawned them; the SSE stream is a *different*
request that must attach to the task). The app lifespan cancels stragglers on
shutdown.

**Revisit if:** more than one instance (a client could hit the instance not
running its incident), or runs must survive a deploy → a queue + shared state.

## Decision 3 — Postgres is the record; the in-memory registry is disposable

`_RUNS: dict[str, IncidentRun]` holds, per live run: its buffered events and the
set of subscriber queues. This is what a queue's result backend would replace.
Stated limitations (all acceptable at demo scope):

- A restart loses in-flight runs — the finished Postgres row is safe, an
  in-flight one is gone; the client's SSE drops and 404s on reconnect.
- Single-instance only.
- Bounded: `_MAX_RETAINED = 50`, oldest finished runs evicted.

The reconciliation rule: **SSE is never made reliable — it's made disposable.** A
client that connects late or reconnects replays the buffer, and once the run is
terminal it does a final `GET /api/incidents/{id}` for the authoritative
`RunRecord`. If SSE had never existed the product would still be correct.

## The event schema

`core/events.py`, `SCHEMA_VERSION = 1`. One coarse event per user-visible
milestone (`triage.*`, `retrieve.*`, `tool_call`, `synthesis.*`, `grounding.*`,
`guardrail.*`, `disposition`, `error`, `finished`). `diagnose(on_event=...)` is
the only producer; `on_event=None` (CLI, eval runner) is a behaviourless no-op —
the blessed eval baseline is unaffected. The frontend's `web/src/lib/timeline.js`
reducer is pinned to this version.

## Consequences

- One deployable artifact: a Node build stage compiles `web/` → `web/dist/`,
  copied into the app image; `app.py` mounts it as the SPA (after the API
  routes) when the directory exists. Dev runs two processes (uvicorn + `vite`,
  the latter proxying `/api` to `:8000`).
- The CLI and the dashboard are now two thin skins over the same `core/` — the
  API wraps `store.list_runs / get_run / record_run / resolve_approvals`
  unchanged, exactly as the CLI does.
- No auth (SPEC non-goal for v1). A single shared instance.
