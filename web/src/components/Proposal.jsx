import { useState } from "react";
import { AlertTriangle, ChevronRight } from "lucide-react";
import { Term, Badge, Label, Panel } from "./ui.jsx";
import { fmtTime } from "../lib/format.js";
import ToolCall from "./evidence/ToolCall.jsx";
import RunbookQuote from "./evidence/RunbookQuote.jsx";

// The full run anatomy: triage → retrieval → investigation (native evidence per
// tool call) → diagnosis → remediation (each step grounded in the real runbook)
// → guardrail trace → disposition.
export default function Proposal({ record: r }) {
  const d = r.diagnosis;
  const verdicts = Object.fromEntries((r.guardrail?.verdicts || []).map((v) => [v.step_index, v]));
  const primaryPath = r.retrieved?.[0]?.path;

  return (
    <div className="space-y-6">
      <Block label="triage" hint="triage">
        <span className="text-[var(--color-ink)]">{r.triage_category}</span>{" "}
        <span className="text-[var(--color-ink-faint)]">({r.triage_confidence})</span>
        <p className="mt-1 leading-relaxed">{r.triage_rationale}</p>
      </Block>

      {r.retrieved?.length > 0 && <Retrieval chunks={r.retrieved} />}

      {r.tool_calls?.length > 0 && (
        <section>
          <Label hint="read-only-tools">investigation · {r.tool_calls.length} tool call(s)</Label>
          <div className="space-y-2">
            {r.tool_calls.map((t, i) => (
              <ToolCall key={i} call={t} />
            ))}
          </div>
        </section>
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
          <p className="text-sm">
            <span className="text-[var(--color-ink-faint)]">root cause — </span>
            <span className="text-[var(--color-ink)]">{d.root_cause}</span>
          </p>
          {d.evidence?.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs text-[var(--color-ink-muted)]">
              {d.evidence.map((e, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-[var(--color-ink-faint)]">›</span>
                  {e}
                </li>
              ))}
            </ul>
          )}

          <div className="mt-4">
            <Label hint="grounding">remediation</Label>
            <ol className="space-y-3.5">
              {(d.remediation_steps || []).map((s, i) => {
                const v = verdicts[i];
                const sc =
                  (v?.classification || (s.state_changing ? "state-changing" : "read-only")) ===
                  "state-changing";
                return (
                  <li key={i} className="text-sm">
                    <div className="flex items-start gap-2">
                      <span className="mt-0.5 font-mono text-xs text-[var(--color-ink-faint)]">
                        {i + 1}
                      </span>
                      <Badge tone={sc ? "warn" : "neutral"}>
                        {sc ? "state-changing" : "read-only"}
                      </Badge>
                      <span className="text-[var(--color-ink)]">{s.action}</span>
                    </div>
                    <div className="mt-1 pl-6">
                      <RunbookQuote quote={s.runbook_quote} path={primaryPath} />
                      {v?.model_disagreed && (
                        <p className="mt-1 flex items-center gap-1 text-xs text-[var(--color-warn)]">
                          <AlertTriangle size={12} /> the model self-labelled this differently — the
                          guardrail's independent verdict: {v.classification}
                          {v.reason ? ` (${v.reason})` : ""}
                        </p>
                      )}
                    </div>
                  </li>
                );
              })}
              {(!d.remediation_steps || d.remediation_steps.length === 0) && (
                <li className="text-sm text-[var(--color-ink-faint)]">
                  no grounded steps survived — the run escalates
                </li>
              )}
            </ol>
          </div>

          {(r.guardrail?.regenerated_for_grounding ||
            (r.guardrail?.second_pass_concerns || []).length > 0) && (
            <div className="mt-4 rounded border-l-2 border-[var(--color-warn)] bg-[var(--color-surface-2)] px-3 py-2 text-xs text-[var(--color-ink-muted)]">
              <Label>guardrail trace</Label>
              {r.guardrail.regenerated_for_grounding && (
                <p>
                  S3 · a step failed the grounding check → synthesis regenerated once
                  {r.guardrail.dropped_ungrounded > 0 &&
                    ` → ${r.guardrail.dropped_ungrounded} step(s) still ungrounded, dropped`}
                </p>
              )}
              {(r.guardrail.second_pass_concerns || []).map((c, i) => (
                <p key={i}>
                  2nd pass · step {c.step_index + 1}: {c.kind} — {c.detail}
                </p>
              ))}
            </div>
          )}
        </Panel>
      ) : (
        <Block label="diagnosis">
          <span className="text-[var(--color-ink-faint)]">
            {r.status === "short-circuited"
              ? "triage short-circuited this alert — the loop did not run"
              : "synthesis produced no parseable diagnosis — escalated with the evidence above"}
          </span>
        </Block>
      )}

      <DispositionTrace record={r} />

      {r.approvals?.length > 0 && (
        <Block label="approvals" hint="approval-gate">
          <ul className="space-y-1.5 font-mono text-xs">
            {r.approvals.map((a) => (
              <li key={a.id}>
                <span className="text-[var(--color-ink-faint)]">step {a.step_index + 1}</span>{" "}
                <span className="text-[var(--color-ink)]">{a.state}</span>
                {a.resolved_by && ` · ${a.resolved_by}`}
                {a.resolved_at && ` · ${fmtTime(a.resolved_at)}`}
                {a.note && (
                  <p className="mt-0.5 pl-4 not-italic text-[var(--color-ink-muted)]">“{a.note}”</p>
                )}
              </li>
            ))}
          </ul>
        </Block>
      )}
    </div>
  );
}

function Retrieval({ chunks }) {
  const [open, setOpen] = useState(false);
  return (
    <section>
      <Label hint="hybrid-search">retrieval · {chunks.length} chunk(s)</Label>
      <div className="space-y-1.5">
        {chunks.map((c, i) => {
          const rr = c.scores?.rerank;
          return (
            <div key={i} className="flex items-center gap-3 font-mono text-xs">
              <span className="text-[var(--color-ink-faint)]">{i + 1}</span>
              <span className="min-w-0 flex-1 truncate text-[var(--color-ink-muted)]">
                {c.path || c.title}
              </span>
              {rr != null && (
                <span className="flex items-center gap-1.5">
                  <span className="h-1 w-16 overflow-hidden rounded bg-[var(--color-surface-2)]">
                    <span
                      className="block h-full bg-[var(--color-accent)]"
                      style={{ width: `${Math.max(4, Math.min(100, (rr / 8) * 100))}%` }}
                    />
                  </span>
                  <span className="text-[0.65rem] text-[var(--color-ink-faint)]">
                    {rr.toFixed(1)}
                  </span>
                </span>
              )}
            </div>
          );
        })}
      </div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="mt-1.5 flex items-center gap-1 font-mono text-[0.68rem] text-[var(--color-ink-faint)] hover:text-[var(--color-ink)]"
      >
        <ChevronRight size={11} className={open ? "rotate-90" : ""} />
        vector ∥ full-text → RRF → rerank
      </button>
      {open && (
        <p className="mt-1 max-w-xl text-[0.72rem] leading-relaxed text-[var(--color-ink-muted)]">
          Two searches run in parallel — dense <Term term="embedding">embedding</Term> similarity and
          Postgres keyword full-text — fused with <Term term="rrf">Reciprocal Rank Fusion</Term>,
          then the top ~30 are re-scored by a <Term term="cross-encoder">cross-encoder</Term>. The
          bar is the rerank score.
        </p>
      )}
    </section>
  );
}

function DispositionTrace({ record: r }) {
  if (!r.disposition) return null;
  const steps = [
    ["grounded remediation exists?", r.diagnosis?.remediation_steps?.length > 0],
    [
      "any step state-changing?",
      (r.guardrail?.verdicts || []).some((v) => v.classification === "state-changing"),
    ],
  ];
  const note = {
    auto: "read-only and grounded — safe to apply automatically",
    "needs-approval": "a human must approve the state-changing step(s) before this resolves",
    escalate: "no grounded fix — handed to a human with the evidence",
  }[r.disposition];
  return (
    <section>
      <Label>disposition</Label>
      <div className="panel p-3.5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs text-[var(--color-ink-muted)]">
          {steps.map(([q, a], i) => (
            <span key={i}>
              {q} <span className="text-[var(--color-ink)]">{a ? "yes" : "no"}</span>
              {i < steps.length - 1 && <span className="ml-3 text-[var(--color-ink-faint)]">→</span>}
            </span>
          ))}
          <span className="text-[var(--color-ink-faint)]">→</span>
          <span className="font-semibold text-[var(--color-ink)]">{r.disposition}</span>
        </div>
        <p className="mt-1.5 text-xs text-[var(--color-ink-muted)]">{note}</p>
      </div>
    </section>
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
