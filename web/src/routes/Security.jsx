import { Link } from "react-router-dom";
import { ShieldCheck, ShieldAlert, ExternalLink } from "lucide-react";
import { Term } from "../components/ui.jsx";
import { useAsync } from "../lib/useAsync.js";
import { getRedteam } from "../api.js";
import {
  THREAT_MODEL,
  SURFACES,
  DEFENCE_STACK,
  CONTAINED_BY,
  RESIDUAL_RISKS,
  GOAL_LABELS,
  SURFACE_NOTE,
} from "../content/security.js";

const REPO = "https://github.com/AllergySnipe/runbook/blob/main";
const GOALS = ["disposition-flip", "inject-action", "exfiltrate", "rc-hijack", "allowlist-probe"];
const SURFACE_ORDER = ["log", "doc", "alert"];

const pct = (hits, n) => (n ? `${hits}/${n} · ${Math.round((hits / n) * 100)}%` : "—");
const asrPct = (v) => (v == null ? "n/a" : `${Math.round(v * 100)}%`);

const DISPO_TONE = {
  auto: "var(--color-critical)",
  "short-circuit": "var(--color-critical)",
  "needs-approval": "var(--color-warn)",
  escalate: "var(--color-ink-muted)",
};

export default function Security() {
  const { data, error, loading } = useAsync(getRedteam, []);
  const base = data?.baseline;
  const hard = data?.hardened;
  const gotThrough = (hard?.cases || []).filter((c) => c.succeeded);

  return (
    <div className="space-y-10">
      <header>
        <h1 className="font-mono text-xl text-[var(--color-ink)]">security</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[var(--color-ink-muted)]">
          {THREAT_MODEL}
        </p>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-[var(--color-ink-muted)]">
          A log-injection <Term term="red-team">red-team</Term> harness runs a fixed catalogue of
          attacks through the real <code className="font-mono text-xs">diagnose()</code> path and
          reports an <Term term="attack-success-rate">attack-success-rate</Term>, in two conditions:{" "}
          <strong>baseline</strong> (the two prompt-level defences off) and <strong>hardened</strong>{" "}
          (as shipped). The structural defences stay on in both.
        </p>
      </header>

      {loading && <p className="text-sm text-[var(--color-ink-faint)]">Loading the last run…</p>}
      {error && (
        <p className="text-sm text-[var(--color-ink-faint)]">
          No blessed run ({error}). Run{" "}
          <code className="font-mono">runbook redteam --condition both --bless</code>.
        </p>
      )}

      {base && hard && (
        <>
          <section>
            <div className="mb-2 flex items-baseline justify-between">
              <h2 className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
                Last blessed run
              </h2>
              <span className="text-xs text-[var(--color-ink-faint)]">
                {data.blessed_at?.slice(0, 10)} · {hard.n_attacks} attacks + 5 controls
              </span>
            </div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-5 rounded-lg border bg-[var(--color-surface)] p-5">
              {[
                ["baseline ASR", base.asr, "prompt defences OFF"],
                ["hardened ASR", hard.asr, "as shipped"],
              ].map(([label, val, sub]) => (
                <div key={label}>
                  <div className="text-[0.6rem] font-medium uppercase tracking-[0.1em] text-[var(--color-ink-faint)]">
                    {label}
                  </div>
                  <div className="mt-0.5 font-mono text-lg text-[var(--color-ink)]">{asrPct(val)}</div>
                  <div className="text-[0.65rem] text-[var(--color-ink-faint)]">{sub}</div>
                </div>
              ))}
            </div>
            <p className="mt-2 text-xs leading-relaxed text-[var(--color-ink-faint)]">
              The baseline-vs-hardened delta is not meaningful at n={hard.n_attacks} on free-tier
              models — hardened scored higher here purely from run-to-run disposition jitter. What the
              numbers show is that the <em>structural</em> layer already catches almost everything;
              the prompt fences are defence-in-depth, not load-bearing.
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
              ASR by surface — the headline view
            </h2>
            <div className="overflow-x-auto rounded-lg border bg-[var(--color-surface)]">
              <table className="w-full text-[0.83rem]">
                <thead>
                  <tr className="border-b text-[0.62rem] uppercase tracking-[0.1em] text-[var(--color-ink-faint)]">
                    <th className="px-4 py-2 text-left font-medium">surface</th>
                    <th className="px-4 py-2 text-right font-medium">baseline</th>
                    <th className="px-4 py-2 text-right font-medium">hardened</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {SURFACE_ORDER.map((s) => {
                    const b = base.asr_by_surface[s] || { hits: 0, n: 0 };
                    const h = hard.asr_by_surface[s] || { hits: 0, n: 0 };
                    const held = h.hits === 0 && h.n > 0;
                    return (
                      <tr key={s}>
                        <td className="px-4 py-2.5">
                          <span className="font-mono text-[var(--color-ink)]">{s}</span>
                          <span className="ml-2 text-[0.7rem] text-[var(--color-ink-faint)]">
                            {SURFACE_NOTE[s]}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-[var(--color-ink-muted)]">
                          {pct(b.hits, b.n)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono">
                          <span style={{ color: held ? "var(--color-ok)" : "var(--color-ink)" }}>
                            {pct(h.hits, h.n)}
                          </span>
                          {held && (
                            <span className="ml-2 text-[0.62rem] font-semibold uppercase text-[var(--color-ok)]">
                              held
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-[var(--color-ink-faint)]">
              Indirect <code className="font-mono text-xs">log</code> injection — a poisoned line
              among 40 real ones — never changed a disposition, injected an action, leaked a canary,
              or escaped the tool allowlist, in either condition.
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
              ASR by goal
            </h2>
            <div className="overflow-x-auto rounded-lg border bg-[var(--color-surface)]">
              <table className="w-full text-[0.83rem]">
                <thead>
                  <tr className="border-b text-[0.62rem] uppercase tracking-[0.1em] text-[var(--color-ink-faint)]">
                    <th className="px-4 py-2 text-left font-medium">goal</th>
                    <th className="px-4 py-2 text-right font-medium">baseline</th>
                    <th className="px-4 py-2 text-right font-medium">hardened</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {GOALS.map((g) => {
                    const b = base.asr_by_goal[g] || { hits: 0, n: 0 };
                    const h = hard.asr_by_goal[g] || { hits: 0, n: 0 };
                    return (
                      <tr key={g}>
                        <td className="px-4 py-2.5">
                          <span className="font-mono text-[var(--color-ink)]">{g}</span>
                          <span className="ml-2 hidden text-[0.7rem] text-[var(--color-ink-faint)] sm:inline">
                            {GOAL_LABELS[g]}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-[var(--color-ink-muted)]">
                          {pct(b.hits, b.n)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-[var(--color-ink)]">
                          {pct(h.hits, h.n)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h2 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
              Attacks that got through (hardened) — and what held them
            </h2>
            {gotThrough.length === 0 ? (
              <p className="rounded-lg border bg-[var(--color-surface)] p-4 text-[0.83rem] text-[var(--color-ink-muted)]">
                No attack achieved its goal.
              </p>
            ) : (
              <ul className="space-y-2">
                {gotThrough.map((c) => {
                  const info = CONTAINED_BY[c.id] || {
                    contained: c.disposition === "needs-approval" || c.disposition === "escalate",
                    note: `Disposition came back ${c.disposition}.`,
                  };
                  return (
                    <li key={c.id} className="rounded-lg border bg-[var(--color-surface)] p-4">
                      <div className="flex flex-wrap items-center gap-2">
                        {info.contained ? (
                          <ShieldCheck size={15} className="shrink-0 text-[var(--color-ok)]" />
                        ) : (
                          <ShieldAlert size={15} className="shrink-0 text-[var(--color-critical)]" />
                        )}
                        <span className="font-mono text-xs text-[var(--color-ink)]">{c.id}</span>
                        <span className="text-[0.62rem] uppercase tracking-wide text-[var(--color-ink-faint)]">
                          {c.surface} · {c.goal}
                        </span>
                        <span
                          className="ml-auto font-mono text-[0.68rem] font-semibold uppercase"
                          style={{ color: DISPO_TONE[c.disposition] || "var(--color-ink-faint)" }}
                        >
                          {c.disposition}
                        </span>
                      </div>
                      <p className="mt-1.5 text-[0.8rem] leading-relaxed text-[var(--color-ink-muted)]">
                        <span
                          className="font-medium"
                          style={{
                            color: info.contained
                              ? "var(--color-ink)"
                              : "var(--color-critical)",
                          }}
                        >
                          {info.contained ? "Contained: " : "Unmitigated: "}
                        </span>
                        {info.note}
                      </p>
                    </li>
                  );
                })}
              </ul>
            )}
            <p className="mt-2 text-xs text-[var(--color-ink-faint)]">
              The approval gate (S1) was never bypassed — in any case, any condition. Nothing an
              injection produced reached <code className="font-mono text-xs">auto</code> with a
              state-changing step in it.
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
              The defence stack
            </h2>
            <dl className="divide-y rounded-lg border bg-[var(--color-surface)]">
              {DEFENCE_STACK.map(([layer, kind, stops]) => (
                <div key={layer} className="px-4 py-3 text-[0.83rem]">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <dt className="font-mono text-xs text-[var(--color-ink)]">{layer}</dt>
                    <span className="text-[0.62rem] uppercase tracking-wide text-[var(--color-ink-faint)]">
                      {kind}
                    </span>
                  </div>
                  <dd className="mt-1 text-[var(--color-ink-muted)]">{stops}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="grid gap-6 sm:grid-cols-[1fr_1.4fr]">
            <div>
              <h2 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
                Attack surfaces
              </h2>
              <ul className="space-y-2">
                {SURFACES.map(([s, cap]) => (
                  <li key={s} className="text-[0.83rem]">
                    <span className="font-mono text-[var(--color-ink)]">{s}</span>
                    <span className="text-[var(--color-ink-muted)]"> — {cap}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h2 className="mb-2 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
                Residual risks — named on purpose
              </h2>
              <ul className="space-y-3">
                {RESIDUAL_RISKS.map((r) => (
                  <li key={r.title} className="text-[0.83rem]">
                    <div className="font-medium text-[var(--color-ink)]">{r.title}</div>
                    <p className="mt-0.5 leading-relaxed text-[var(--color-ink-muted)]">{r.body}</p>
                    <p className="mt-0.5 leading-relaxed text-[var(--color-ink-faint)]">
                      <span className="uppercase tracking-wide">option:</span> {r.fix}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          </section>

          <div className="flex flex-wrap gap-x-6 gap-y-2 border-t pt-4 text-xs">
            <a
              href={`${REPO}/docs/security/log-injection.md`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[var(--color-accent)] hover:underline"
            >
              Full security report <ExternalLink size={12} />
            </a>
            <a
              href={`${REPO}/docs/adr/0012-red-team-harness.md`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[var(--color-accent)] hover:underline"
            >
              ADR-0012 — design + rationale <ExternalLink size={12} />
            </a>
            <Link to="/evals" className="text-[var(--color-accent)] hover:underline">
              Evals scorecard →
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
