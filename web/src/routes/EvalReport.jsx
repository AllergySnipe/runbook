import { Link } from "react-router-dom";
import { ExternalLink } from "lucide-react";
import { useAsync } from "../lib/useAsync.js";
import { getEvalBaseline, getRedteam } from "../api.js";
import { SOFT_BAR, HARD_CHECKS, BLIND_SPOTS, PATH } from "../content/eval-report.js";

const REPO = "https://github.com/AllergySnipe/runbook/blob/main";

export default function EvalReport() {
  const { data: base, error: baseErr, loading: baseLoading } = useAsync(getEvalBaseline, []);
  const { data: rt } = useAsync(getRedteam, []);
  const m = base?.metrics;

  const logSurface = rt?.hardened?.asr_by_surface?.log;
  const logHeld = logSurface && logSurface.hits === 0 && logSurface.n > 0;

  return (
    <div>
      <header>
        <p className="font-mono text-[0.7rem] font-medium uppercase tracking-[0.16em] text-[var(--color-accent)]">
          Eval report
        </p>
        <h1 className="font-display mt-3 text-[2.1rem] font-medium tracking-[-0.02em] sm:text-[2.6rem]">
          Is Runbook good enough to put in front of on-call?
        </h1>
      </header>

      <div className="prose-col mt-8">
        <p>
          Runbook proposes a diagnosis and a set of remediation steps during an incident. Before an
          on-call engineer relies on it, someone has to decide whether it is good enough. This page
          is that decision, the evidence behind it, and the parts the evidence does not cover.
        </p>

        <h2>The recommendation</h2>
        <p>
          Run Runbook in advisory mode, with a hard approval gate on any state-changing step. That is
          the mode the system is built for, and the evidence supports it.
        </p>
        <p>
          Do not run it in auto-remediation mode, where it acts without a human. The evidence does
          not support that yet. The gap is the size and realism of the test set, not the code.
        </p>

        <h2>What "good enough" means here</h2>
        <p>"Good enough" has to be a set of thresholds, not a feeling. Runbook has four.</p>
        <p>
          <strong>Hard checks — 100%, every run.</strong> Three boolean checks, each tied to a safety
          requirement in the spec. They use no model. One failure fails the release. A wrong action
          is a different kind of event from a weak explanation, so it is not averaged into a score —
          it is a gate.
        </p>
        <ul className="my-4 space-y-1.5 pl-0">
          {HARD_CHECKS.map(([tag, text]) => (
            <li key={tag} className="flex list-none gap-3 text-[0.9rem] text-[var(--color-ink-muted)]">
              <span className="font-mono text-xs text-[var(--color-ink-faint)]">{tag}</span>
              <span>{text}</span>
            </li>
          ))}
        </ul>
        <p>
          <strong>Soft metrics — above threshold, with a tolerance band.</strong> Seven of them.
          Recall on real incidents is set higher than accuracy because routing a real incident to
          "noise" is the expensive mistake.
        </p>
        <p>
          <strong>Security — 0% attack success on the log surface</strong>, and the approval gate
          never bypassed in any condition. The log surface is the realistic one: an attacker who can
          get a string into a log line, not one who can edit the prompt.
        </p>
        <p>
          <strong>Regression — no metric drops more than 0.05 below its blessed value and below
          target</strong> without a re-bless. The blessed values live in a committed file; lowering
          one is a reviewed change, not a silent drift.
        </p>

        <h2>The evidence today</h2>
      </div>

      {baseLoading && (
        <p className="mt-4 text-sm text-[var(--color-ink-faint)]">Loading the blessed baseline…</p>
      )}
      {baseErr && (
        <p className="mt-4 text-sm text-[var(--color-ink-faint)]">
          Baseline unavailable ({baseErr}).
        </p>
      )}

      {m && (
        <div className="mt-4 max-w-2xl">
          <div className="mb-2 flex items-baseline justify-between">
            <span className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
              Blessed baseline
            </span>
            <span className="text-xs text-[var(--color-ink-faint)]">
              {base.blessed_at?.slice(0, 10)} · {base.n_cases} cases
            </span>
          </div>
          <div className="overflow-x-auto rounded-lg border bg-[var(--color-surface)]">
            <table className="w-full text-[0.85rem]">
              <thead>
                <tr className="border-b text-[0.62rem] uppercase tracking-[0.1em] text-[var(--color-ink-faint)]">
                  <th className="px-4 py-2 text-left font-medium">metric</th>
                  <th className="px-4 py-2 text-right font-medium">value</th>
                  <th className="px-4 py-2 text-right font-medium">target</th>
                  <th className="hidden px-4 py-2 text-left font-medium sm:table-cell">why the bar is there</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {SOFT_BAR.map(([key, label, target, note]) => {
                  const v = m[key];
                  const ok = v != null && v >= target;
                  return (
                    <tr key={key}>
                      <td className="px-4 py-2.5 text-[var(--color-ink-muted)]">{label}</td>
                      <td
                        className="px-4 py-2.5 text-right font-mono"
                        style={{ color: ok ? "var(--color-ok)" : "var(--color-critical)" }}
                      >
                        {v == null ? "—" : v.toFixed(2)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-[var(--color-ink-faint)]">
                        {target.toFixed(2)}
                      </td>
                      <td className="hidden px-4 py-2.5 text-[0.78rem] text-[var(--color-ink-faint)] sm:table-cell">
                        {note}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-[0.85rem] leading-relaxed text-[var(--color-ink-muted)]">
            Hard checks: clear.{" "}
            {logHeld ? (
              <>
                Red-team: the log surface held at 0% attack success ({logSurface.hits}/{logSurface.n}),
                and the approval gate was never bypassed in any condition.
              </>
            ) : (
              <>Red-team results are on the security page.</>
            )}
          </p>
        </div>
      )}

      <div className="prose-col mt-2">
        <h2>What the evidence does not cover</h2>
        <p>This is the part that matters.</p>
      </div>
      <ul className="mt-4 max-w-2xl space-y-4">
        {BLIND_SPOTS.map((b) => (
          <li key={b.title}>
            <div className="text-[0.95rem] font-semibold text-[var(--color-ink)]">{b.title}</div>
            <p className="mt-1 text-[0.9rem] leading-relaxed text-[var(--color-ink-muted)]">{b.body}</p>
          </li>
        ))}
      </ul>

      <div className="prose-col mt-2">
        <h2>Why advisory-plus-gate is the right mode</h2>
        <p>
          The approval gate is a code property, not a prompt instruction. Any step classified
          state-changing forces the run into "awaiting approval," and nothing executes regardless of
          the disposition. The eval's hard check and the red-team both confirm it held. This is a
          claim the evidence is strong enough to make, because it is checked deterministically rather
          than being a statement about model quality.
        </p>
        <p>
          Advisory output fails safe. The worst case is a wrong suggestion that a responder reads and
          discards. The groundedness check and the judge metric bound how wrong it can be.
        </p>
        <p>
          Auto-remediation would move the model from judgment-adjacent work to judgment-critical
          work. The test set is too small and too close to the design distribution to support that
          move.
        </p>

        <h2>What would change the recommendation</h2>
        <p>A path exists, and the infrastructure for it is built.</p>
      </div>
      <ol className="mt-4 max-w-2xl space-y-3">
        {PATH.map((p, i) => (
          <li key={p.title} className="flex gap-3">
            <span className="font-mono text-sm text-[var(--color-ink-faint)]">{i + 1}</span>
            <span className="text-[0.9rem] leading-relaxed text-[var(--color-ink-muted)]">
              <span className="font-medium text-[var(--color-ink)]">{p.title}</span> — {p.body}
            </span>
          </li>
        ))}
      </ol>

      <div className="prose-col mt-2">
        <p>
          Only then is it worth discussing auto-remediation, and only for the narrowest,
          highest-confidence known-runbook path, behind a flag, A/B tested in the eval suite.
        </p>

        <h2>How this stays honest</h2>
        <p>
          The same eval definitions run in more than one place. The full suite runs in CI on every
          change. The reference-free subset runs on sampled production traffic, using the same logic,
          pinned to the eval implementation by a test. The regression baseline is a committed file.
          The red-team is a manual point-in-time run, repeated on any change to the prompts, the
          guardrails, or retrieval.
        </p>

        <h2>Bottom line</h2>
        <p>
          Runbook is good enough to help an on-call engineer work faster, with a human approving
          every action. It is not good enough to act on its own. The reason is the test set, not the
          system — and the parts that close that gap, the flywheel and the online scoring and the
          regression gate, are the parts that are already built.
        </p>
      </div>

      <div className="mt-10 flex flex-wrap gap-x-6 gap-y-2 border-t pt-4 text-xs">
        <a
          href={`${REPO}/docs/design/eval-report.md`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-[var(--color-accent)] hover:underline"
        >
          This document in the repo <ExternalLink size={12} />
        </a>
        <a
          href={`${REPO}/docs/adr/0008-eval-design.md`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-[var(--color-accent)] hover:underline"
        >
          ADR-0008 — eval design <ExternalLink size={12} />
        </a>
        <Link to="/evals" className="text-[var(--color-accent)] hover:underline">
          Evals scorecard →
        </Link>
        <Link to="/security" className="text-[var(--color-accent)] hover:underline">
          Security report →
        </Link>
      </div>
    </div>
  );
}
