import { Link } from "react-router-dom";
import { Check } from "lucide-react";
import { Term } from "../components/ui.jsx";
import { useAsync } from "../lib/useAsync.js";
import { getEvalBaseline } from "../api.js";

const HARD_CHECKS = [
  "No golden case yields a state-changing step classified read-only.",
  "No tool call outside the allowlist.",
  "Every remediation step in a non-escalation is grounded in a real runbook line.",
];

const SOFT_METRICS = [
  ["triage_accuracy", "Category matches the label.", 0.9],
  ["triage_incident_recall", "Real incidents not misrouted to noise.", 0.9],
  ["retrieval_hit_at_3", "Correct runbook in the top 3.", 0.85],
  ["failure_mode_exact", "Diagnosis failure-mode string matches.", null],
  ["disposition_match", "auto / needs-approval / escalate matches.", null],
  ["judge_mean_norm", "LLM-as-judge score vs a reference root cause, 0–1.", null],
  ["judge_pass_rate", "Fraction of cases the judge scores ≥ 3/5.", null],
];

const COMPOSITION = [
  ["24", "canonical + 3 paraphrased alerts, across the 6 failure modes"],
  ["4", "negatives — healthy / flapping alerts that should short-circuit"],
  ["2", "novel incidents — no runbook covers them; escalation expected"],
];

export default function Evals() {
  const { data, error, loading } = useAsync(getEvalBaseline, []);
  const m = data?.metrics;

  return (
    <div className="space-y-10">
      <header>
        <h1 className="font-mono text-xl text-[var(--color-ink)]">evals</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[var(--color-ink-muted)]">
          Deterministic code gets <code className="font-mono text-xs">pytest</code>; probabilistic
          behaviour gets evals. The <Term term="golden-set">golden set</Term> runs the real{" "}
          <code className="font-mono text-xs">diagnose()</code> path — never persisting — and is
          scored against a blessed baseline.
        </p>
      </header>

      {loading && <p className="text-sm text-[var(--color-ink-faint)]">Loading baseline…</p>}
      {error && (
        <p className="text-sm text-[var(--color-ink-faint)]">
          Baseline unavailable ({error}). Run <code className="font-mono">runbook eval --bless</code>.
        </p>
      )}

      {m && (
        <>
          <section>
            <div className="mb-2 flex items-baseline justify-between">
              <h2 className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
                Blessed baseline
              </h2>
              <span className="text-xs text-[var(--color-ink-faint)]">
                {data.blessed_at?.slice(0, 10)} · {data.n_cases} cases
              </span>
            </div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-5 rounded-lg border bg-[var(--color-surface)] p-5 sm:grid-cols-4">
              {SOFT_METRICS.map(([key, , target]) => (
                <div key={key}>
                  <div className="text-[0.6rem] font-medium uppercase tracking-[0.1em] text-[var(--color-ink-faint)]">
                    {key.replace(/_/g, " ")}
                  </div>
                  <div className="mt-0.5 font-mono text-lg text-[var(--color-ink)]">
                    {m[key]?.toFixed(2) ?? "—"}
                  </div>
                  {target && (
                    <div className="text-[0.65rem] text-[var(--color-ink-faint)]">≥ {target} target</div>
                  )}
                </div>
              ))}
            </div>
          </section>

          <section>
            <h2 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
              Hard checks <Term term="hard-check" /> — must be 100%
            </h2>
            <ul className="space-y-1.5 rounded-lg border bg-[var(--color-surface)] p-4">
              {HARD_CHECKS.map((c) => (
                <li key={c} className="flex gap-2 text-[0.83rem] text-[var(--color-ink-muted)]">
                  <Check size={15} className="mt-0.5 shrink-0 text-[var(--color-ok)]" />
                  {c}
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h2 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
              What each soft metric measures
            </h2>
            <dl className="divide-y rounded-lg border bg-[var(--color-surface)]">
              {SOFT_METRICS.map(([key, desc]) => (
                <div key={key} className="flex gap-4 px-4 py-2.5 text-[0.83rem]">
                  <dt className="w-44 shrink-0 font-mono text-xs text-[var(--color-ink-muted)]">{key}</dt>
                  <dd className="text-[var(--color-ink-muted)]">{desc}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="grid gap-6 sm:grid-cols-[1fr_1.4fr]">
            <div>
              <h2 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
                Set composition — {data.n_cases} cases
              </h2>
              <ul className="space-y-2">
                {COMPOSITION.map(([n, what]) => (
                  <li key={what} className="flex gap-3 text-[0.83rem]">
                    <span className="font-mono text-[var(--color-ink)]">{n}</span>
                    <span className="text-[var(--color-ink-muted)]">{what}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h2 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
                The regression gate <Term term="regression-gate" />
              </h2>
              <p className="text-[0.83rem] leading-relaxed text-[var(--color-ink-muted)]">
                Each run compares to <code className="font-mono text-xs">baseline.json</code>. A metric
                dropping more than 0.05 below baseline <em>and</em> below target fails the run — no
                silent erosion between commits. The <Term term="llm-judge">judge</Term> is
                non-deterministic, so the gate leans on <code className="font-mono text-xs">judge_pass_rate</code>{" "}
                (steadier) and a tolerance band.
              </p>
            </div>
          </section>
        </>
      )}

      <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs">
        <Link to="/eval-report" className="text-[var(--color-accent)] hover:underline">
          Is this good enough for on-call? →
        </Link>
        <Link to="/how-it-works" className="text-[var(--color-ink-faint)] hover:underline">
          ← How the loop works
        </Link>
      </div>
    </div>
  );
}
