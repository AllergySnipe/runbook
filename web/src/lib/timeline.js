// Pure: fold the SSE event stream into an ordered list of timeline rows the
// console view renders. Event shapes must match core/events.py. The SSE stream
// replays its whole buffer on every (re)connect, so this must be idempotent.

const ROWS = {
  "cache.hit": (d) => ({
    phase: "cache",
    detail: `hit · ${(d.similarity ?? 0).toFixed(2)} sim · ${d.age_s ?? 0}s old — triage + retrieval reused`,
    tone: "muted",
    ok: true,
  }),
  "triage.start": () => ({ phase: "triage", detail: "classifying the alert", pending: true }),
  "triage.done": (d) => ({
    phase: "triage",
    detail: `${d.category}${d.low_prior ? " · low prior" : ""}`,
    ok: true,
  }),
  short_circuit: (d) => ({ phase: "triage", detail: `short-circuit · ${d.category}`, tone: "muted" }),
  "retrieve.start": () => ({ phase: "retrieve", detail: "hybrid search", pending: true }),
  "retrieve.done": (d) => ({
    phase: "retrieve",
    detail: `${(d.docs || []).length} doc(s) · ${(d.docs?.[0] || "").split("/").pop()}`,
    ok: true,
  }),
  tool_call: (d) => ({
    phase: d.name,
    detail: Object.entries(d.input || {})
      .map(([k, v]) => `${k}=${v}`)
      .join("  "),
    tone: d.is_error ? "error" : "tool",
    ok: !d.is_error,
    err: d.is_error,
  }),
  redaction: (d) => {
    const kinds = Object.keys(d.kinds || {}).join(", ");
    return {
      phase: "redaction",
      detail: `${d.count} span(s) scrubbed from tool output${kinds ? ` · ${kinds}` : ""}`,
      tone: "warn",
    };
  },
  "synthesis.start": () => ({ phase: "synthesise", detail: "drafting diagnosis", pending: true }),
  "synthesis.done": (d) => ({
    phase: "synthesise",
    detail: `${d.confidence} confidence · ${d.n_steps} step(s)`,
    ok: true,
  }),
  "grounding.regenerated": (d) => ({
    phase: "grounding",
    detail: `${d.issues} ungrounded · regenerating`,
    tone: "warn",
  }),
  "grounding.dropped": (d) => ({
    phase: "grounding",
    detail: `dropped ${d.count} step(s)`,
    tone: "warn",
  }),
  "guardrail.start": () => ({ phase: "guardrail", detail: "classifying actions", pending: true }),
  "guardrail.done": (d) => {
    const sc = (d.verdicts || []).filter((v) => v.classification === "state-changing").length;
    return { phase: "guardrail", detail: `${sc} state-changing step(s)`, ok: true };
  },
  disposition: (d) => ({ phase: "disposition", detail: d.disposition, tone: "strong" }),
  error: (d) => ({ phase: "error", detail: d.message, tone: "error", err: true }),
  finished: (d) => ({ phase: "done", detail: d.status, tone: "strong", ok: true }),
};

export function eventKey(e) {
  return e.type === "tool_call" ? `tool_call:${JSON.stringify(e.data || {})}` : e.type;
}

export function buildTimeline(events) {
  const t0 = events.find((e) => e.t)?.t;
  const rows = [];
  const seen = new Set();
  for (const e of events) {
    const make = ROWS[e.type];
    if (!make) continue;
    const key = eventKey(e);
    if (seen.has(key)) continue;
    seen.add(key);
    if (e.type.endsWith(".done")) {
      const prev = rows.find((r) => r.srcType === `${e.type.slice(0, -5)}.start`);
      if (prev) prev.pending = false;
    }
    rows.push({
      id: key,
      srcType: e.type,
      elapsed: t0 && e.t ? (e.t - t0) / 1000 : null,
      ...make(e.data || {}),
    });
  }
  if (events.some((e) => e.type === "finished" || e.type === "error")) {
    for (const r of rows) r.pending = false;
  }
  return rows;
}

export const isTerminal = (events) =>
  events.some((e) => e.type === "finished" || e.type === "error");

export const fmtElapsed = (s) => {
  if (s == null) return "  ·  ";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `+${m}:${String(sec).padStart(2, "0")}`;
};
