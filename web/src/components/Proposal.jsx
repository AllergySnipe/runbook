import { fmtTime } from "../lib/format.jsx";

const DISPOSITION_NOTE = {
  auto: "Steps are read-only and grounded — nothing needs approval.",
  "needs-approval": "A human must approve the state-changing step(s) before this run resolves.",
  escalate: "No grounded remediation — hand to a human with the evidence above.",
};

export default function Proposal({ record: r }) {
  const d = r.diagnosis;
  const verdicts = Object.fromEntries((r.guardrail?.verdicts || []).map((v) => [v.step_index, v]));

  return (
    <section className="space-y-5">
      <Row label="TRIAGE">
        {r.triage_category} <span className="text-zinc-500">({r.triage_confidence})</span> —{" "}
        {r.triage_rationale}
      </Row>

      {r.retrieved?.length > 0 && (
        <Row label="RETRIEVED">
          <span className="font-mono text-xs">
            {r.retrieved.map((c) => c.path || c.title).join(", ")}
          </span>
        </Row>
      )}

      {r.tool_calls?.length > 0 && (
        <Row label="TOOL CALLS">
          <ul className="space-y-0.5 font-mono text-xs">
            {r.tool_calls.map((t, i) => (
              <li key={i} className={t.is_error ? "text-rose-400" : ""}>
                {t.name}(
                {Object.entries(t.input || {})
                  .map(([k, v]) => `${k}=${v}`)
                  .join(", ")}
                ){t.is_error && " — error"}
              </li>
            ))}
          </ul>
        </Row>
      )}

      {d ? (
        <div className="rounded-lg border border-zinc-800 p-4">
          <div className="flex items-center gap-3">
            <h3 className="text-sm font-semibold text-zinc-200">Diagnosis</h3>
            <span className="text-xs text-zinc-500">
              {d.confidence} confidence · failure mode: {d.failure_mode}
            </span>
          </div>
          <p className="mt-2 text-sm text-zinc-300">
            <span className="text-zinc-500">root cause: </span>
            {d.root_cause}
          </p>
          {d.evidence?.length > 0 && (
            <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-zinc-400">
              {d.evidence.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          )}

          <h4 className="mt-4 text-xs font-semibold text-zinc-500">REMEDIATION</h4>
          <ol className="mt-2 space-y-3">
            {(d.remediation_steps || []).map((s, i) => {
              const v = verdicts[i];
              const cls = v?.classification || (s.state_changing ? "state-changing" : "read-only");
              return (
                <li key={i} className="text-sm">
                  <div className="flex items-start gap-2">
                    <Tag cls={cls} />
                    <span className="text-zinc-200">{s.action}</span>
                  </div>
                  <p className="mt-0.5 pl-1 text-xs text-zinc-500">
                    ⤷ runbook: “{s.runbook_quote}”
                  </p>
                  {v?.model_disagreed && (
                    <p className="mt-0.5 pl-1 text-xs text-amber-400">
                      ⚠ model self-labelled differently — guardrail: {v.classification} ({v.reason})
                    </p>
                  )}
                </li>
              );
            })}
            {(!d.remediation_steps || d.remediation_steps.length === 0) && (
              <li className="text-sm text-zinc-500">(no grounded steps)</li>
            )}
          </ol>

          {r.guardrail?.regenerated_for_grounding && (
            <p className="mt-3 text-xs text-amber-400">
              ⚠ S3: remediation regenerated once for grounding
              {r.guardrail.dropped_ungrounded > 0 &&
                `, then dropped ${r.guardrail.dropped_ungrounded} ungrounded step(s)`}
            </p>
          )}
          {(r.guardrail?.second_pass_concerns || []).map((c, i) => (
            <p key={i} className="mt-1 text-xs text-amber-400">
              ⚠ second pass — step {c.step_index + 1}: {c.kind} — {c.detail}
            </p>
          ))}
        </div>
      ) : (
        <Row label="DIAGNOSIS">
          <span className="text-zinc-500">
            {r.status === "short-circuited"
              ? "triage short-circuited this alert — the loop did not run"
              : "no parseable diagnosis — escalated with the evidence above"}
          </span>
        </Row>
      )}

      {r.disposition && (
        <div className="rounded-lg bg-zinc-900 p-3 text-sm">
          <span className="font-semibold text-zinc-200">disposition: {r.disposition}</span>
          <span className="ml-2 text-zinc-500">{DISPOSITION_NOTE[r.disposition]}</span>
        </div>
      )}

      {r.approvals?.length > 0 && (
        <Row label="APPROVALS">
          <ul className="space-y-1 text-xs">
            {r.approvals.map((a) => (
              <li key={a.id}>
                step {a.step_index + 1}: <span className="text-zinc-200">{a.state}</span>
                {a.resolved_by && ` — ${a.resolved_by}`}
                {a.resolved_at && ` at ${fmtTime(a.resolved_at)}`}
                {a.note && <span className="text-zinc-500"> · “{a.note}”</span>}
              </li>
            ))}
          </ul>
        </Row>
      )}

      <p className="text-xs text-zinc-600">
        {r.iterations} turns · {r.usage?.input_tokens || 0}in/{r.usage?.output_tokens || 0}out
        tokens · {r.elapsed_s}s
      </p>
    </section>
  );
}

function Row({ label, children }) {
  return (
    <div>
      <p className="text-xs font-semibold text-zinc-500">{label}</p>
      <div className="mt-1 text-sm text-zinc-300">{children}</div>
    </div>
  );
}

function Tag({ cls }) {
  const sc = cls === "state-changing";
  return (
    <span
      className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ring-1 ${
        sc
          ? "bg-amber-500/15 text-amber-300 ring-amber-500/30"
          : "bg-zinc-500/15 text-zinc-400 ring-zinc-500/30"
      }`}
    >
      {sc ? "state-changing" : "read-only"}
    </span>
  );
}
