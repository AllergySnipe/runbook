// Pure: fold the SSE event stream into an ordered list of timeline items the
// detail view renders. Kept separate from React so it can be unit-tested and
// reasoned about on its own. Event shapes must match core/events.py.

const LABELS = {
  "triage.start": () => ({ label: "Triaging the alert", pending: true }),
  "triage.done": (d) => ({
    label: `Triage: ${d.category}${d.low_prior ? " (low prior — novel)" : ""}`,
  }),
  short_circuit: (d) => ({ label: `Short-circuited — ${d.category}`, tone: "muted" }),
  "retrieve.start": () => ({ label: "Retrieving the runbook", pending: true }),
  "retrieve.done": (d) => ({ label: `Retrieved: ${(d.docs || []).join(", ")}` }),
  tool_call: (d) => ({
    label: `Tool: ${d.name}(${Object.entries(d.input || {})
      .map(([k, v]) => `${k}=${v}`)
      .join(", ")})`,
    tone: d.is_error ? "error" : "tool",
  }),
  "synthesis.start": () => ({ label: "Synthesising the diagnosis", pending: true }),
  "synthesis.done": (d) => ({
    label: `Diagnosis drafted — ${d.confidence} confidence, ${d.n_steps} step(s)`,
  }),
  "grounding.regenerated": (d) => ({
    label: `S3: ${d.issues} ungrounded step(s) — regenerating once`,
    tone: "warn",
  }),
  "grounding.dropped": (d) => ({
    label: `S3: dropped ${d.count} step(s) still ungrounded`,
    tone: "warn",
  }),
  "guardrail.start": () => ({ label: "Guardrail: classifying actions", pending: true }),
  "guardrail.done": (d) => {
    const sc = (d.verdicts || []).filter((v) => v.classification === "state-changing").length;
    return { label: `Guardrail: ${sc} state-changing step(s)` };
  },
  disposition: (d) => ({ label: `Disposition: ${d.disposition}`, tone: "strong" }),
  error: (d) => ({ label: `Failed: ${d.message}`, tone: "error" }),
  finished: (d) => ({ label: `Finished — ${d.status}`, tone: "strong" }),
};

export function buildTimeline(events) {
  const items = [];
  for (const e of events) {
    const make = LABELS[e.type];
    if (!make) continue;
    // a *.done event clears the pending flag on the matching *.start
    if (e.type.endsWith(".done")) {
      const stem = e.type.slice(0, -5);
      const prev = items.find((it) => it.key === `${stem}.start`);
      if (prev) prev.pending = false;
    }
    items.push({ key: e.type, ...make(e.data || {}) });
  }
  return items;
}

export const isTerminal = (events) =>
  events.some((e) => e.type === "finished" || e.type === "error");
