import { AlertTriangle } from "lucide-react";
import { Term, Badge, Label, Panel } from "./ui.jsx";
import { fmtTime } from "../lib/format.js";

// Interim proposal view — Phase 2 makes this the full "run anatomy" with native
// rendering of each tool result, runbook-quote highlighting, and the guardrail
// trace. For now: the structured record, cleanly laid out.
export default function Proposal({ record: r }) {
  const d = r.diagnosis;
  const verdicts = Object.fromEntries((r.guardrail?.verdicts || []).map((v) => [v.step_index, v]));

  return (
    <div className="space-y-6">
      <Block label="triage" hint="triage">
        <span className="text-[var(--color-ink)]">{r.triage_category}</span>{" "}
        <span className="text-[var(--color-ink-faint)]">({r.triage_confidence})</span> —{" "}
        {r.triage_rationale}
      </Block>

      {r.retrieved?.length > 0 && (
        <Block label="retrieved" hint="hybrid-search">
          <ul className="space-y-1 font-mono text-xs">
            {r.retrieved.map((c, i) => (
              <li key={i} className="text-[var(--color-ink-muted)]">
                <span className="text-[var(--color-ink-faint)]">{i + 1}</span> {c.path || c.title}
              </li>
            ))}
          </ul>
        </Block>
      )}

      {r.tool_calls?.length > 0 && (
        <Block label="investigation" hint="read-only-tools">
          <ul className="space-y-1 font-mono text-xs">
            {r.tool_calls.map((t, i) => (
              <li
                key={i}
                className={t.is_error ? "text-[var(--color-critical)]" : "text-[var(--color-ink-muted)]"}
              >
                <span className="text-[var(--color-accent)]">{t.name}</span>(
                {Object.entries(t.input || {})
                  .map(([k, v]) => `${k}=${v}`)
                  .join(", ")}
                ){t.is_error && " — error"}
              </li>
            ))}
          </ul>
        </Block>
      )}

      {d ? (
        <Panel
          title="diagnosis"
          right={
            <span className="text-[var(--color-ink-faint)]">
              {d.confidence} · {d.failure_mode}
            </span>
          }
        >
          <p className="text-sm text-[var(--color-ink-muted)]">
            <span className="text-[var(--color-ink-faint)]">root cause — </span>
            <span className="text-[var(--color-ink)]">{d.root_cause}</span>
          </p>
          {d.evidence?.length > 0 && (
            <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-[var(--color-ink-muted)]">
              {d.evidence.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          )}

          <div className="mt-4">
            <Label hint="grounding">remediation</Label>
            <ol className="space-y-3">
              {(d.remediation_steps || []).map((s, i) => {
                const v = verdicts[i];
                const sc =
                  (v?.classification || (s.state_changing ? "state-changing" : "read-only")) ===
                  "state-changing";
                return (
                  <li key={i} className="text-sm">
                    <div className="flex items-start gap-2">
                      <Badge tone={sc ? "warn" : "neutral"}>{sc ? "state-changing" : "read-only"}</Badge>
                      <span className="text-[var(--color-ink)]">{s.action}</span>
                    </div>
                    <p className="mt-1 border-l-2 border-[var(--color-border-strong)] pl-2.5 font-mono text-[0.72rem] leading-relaxed text-[var(--color-ink-faint)]">
                      {s.runbook_quote}
                    </p>
                    {v?.model_disagreed && (
                      <p className="mt-1 flex items-center gap-1 text-xs text-[var(--color-warn)]">
                        <AlertTriangle size={12} /> model self-labelled differently — guardrail:{" "}
                        {v.classification}
                      </p>
                    )}
                  </li>
                );
              })}
              {(!d.remediation_steps || d.remediation_steps.length === 0) && (
                <li className="text-sm text-[var(--color-ink-faint)]">
                  no grounded steps — escalated
                </li>
              )}
            </ol>
          </div>

          {r.guardrail?.regenerated_for_grounding && (
            <p className="mt-3 text-xs text-[var(--color-warn)]">
              S3 · remediation regenerated once
              {r.guardrail.dropped_ungrounded > 0 &&
                `, then dropped ${r.guardrail.dropped_ungrounded} ungrounded step(s)`}
            </p>
          )}
          {(r.guardrail?.second_pass_concerns || []).map((c, i) => (
            <p key={i} className="mt-1 text-xs text-[var(--color-warn)]">
              second pass · step {c.step_index + 1}: {c.kind} — {c.detail}
            </p>
          ))}
        </Panel>
      ) : (
        <Block label="diagnosis">
          <span className="text-[var(--color-ink-faint)]">
            {r.status === "short-circuited"
              ? "triage short-circuited this alert — the loop did not run"
              : "no parseable diagnosis — escalated with the evidence above"}
          </span>
        </Block>
      )}

      {r.approvals?.length > 0 && (
        <Block label="approvals" hint="approval-gate">
          <ul className="space-y-1 font-mono text-xs">
            {r.approvals.map((a) => (
              <li key={a.id}>
                step {a.step_index + 1}:{" "}
                <span className="text-[var(--color-ink)]">{a.state}</span>
                {a.resolved_by && ` · ${a.resolved_by}`}
                {a.resolved_at && ` · ${fmtTime(a.resolved_at)}`}
                {a.note && (
                  <span className="text-[var(--color-ink-faint)]"> · “{a.note}”</span>
                )}
              </li>
            ))}
          </ul>
        </Block>
      )}
    </div>
  );
}

function Block({ label, hint, children }) {
  return (
    <section>
      <Label hint={hint}>{label}</Label>
      <div className="text-sm text-[var(--color-ink-muted)]">{children}</div>
    </section>
  );
}
