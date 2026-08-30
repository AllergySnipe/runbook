// Thin wrappers over the FastAPI surface (src/runbook/web_api.py). Same-origin
// in every mode — Vite proxies /api to :8000 in dev, FastAPI serves this SPA in
// prod.

async function json(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const listIncidents = () => fetch("/api/incidents").then(json);

export const getIncident = (id) => fetch(`/api/incidents/${id}`).then(json);

export const listScenarios = () => fetch("/api/scenarios").then(json);

export const startIncident = (body) =>
  fetch("/api/incidents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(json);

export const decide = (id, decision, body) =>
  fetch(`/api/incidents/${id}/${decision}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(json);

// Open the SSE progress stream for a run. `onEvent({type, data})` fires per
// event; the returned function closes the stream. The server ends it with a
// `finished` or `error` event — the caller then re-fetches the authoritative
// record with getIncident().
export function openEventStream(id, onEvent) {
  const es = new EventSource(`/api/incidents/${id}/events`);
  const handler = (type) => (e) => {
    let data = {};
    try {
      data = e.data ? JSON.parse(e.data) : {};
    } catch {
      /* keepalive comments etc. */
    }
    onEvent({ type, data });
  };
  for (const type of EVENT_TYPES) es.addEventListener(type, handler(type));
  es.onerror = () => es.close(); // stream closed by the server, or a real error
  return () => es.close();
}

// Must match core/events.py (SCHEMA_VERSION 1).
export const EVENT_TYPES = [
  "triage.start",
  "triage.done",
  "short_circuit",
  "retrieve.start",
  "retrieve.done",
  "tool_call",
  "synthesis.start",
  "synthesis.done",
  "grounding.regenerated",
  "grounding.dropped",
  "guardrail.start",
  "guardrail.done",
  "disposition",
  "error",
  "finished",
];
