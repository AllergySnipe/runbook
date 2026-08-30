import { Link } from "react-router-dom";
import { ArrowRight, ShieldCheck, Check, Minus } from "lucide-react";
import LoopDiagram from "../components/LoopDiagram.jsx";
import { StatusPill, Term } from "../components/ui.jsx";
import { useAsync } from "../lib/useAsync.js";
import { getEvalBaseline, listIncidents } from "../api.js";
import { SCENARIO_COPY } from "../content/scenarios.js";
import { TAGLINE, PROBLEM, SAFETY, STACK, NON_GOALS } from "../content/copy.js";

export default function Overview() {
  return (
    <div className="space-y-20">
      <Hero />
      <WorkedExamples />
      <TheLoop />
      <Architecture />
      <Safety />
      <Evals />
      <StackAndScope />
    </div>
  );
}

function WorkedExamples() {
  const { data } = useAsync(() => listIncidents({ featured: true }), []);
  if (!data?.length) return null;
  return (
    <section>
      <p className="font-mono text-[0.7rem] font-medium uppercase tracking-[0.16em] text-[var(--color-ink-faint)]">
        Worked examples
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        {data.map((r) => {
          const copy = SCENARIO_COPY[r.scenario] || {};
          return (
            <Link
              key={r.id}
              to={`/incidents/${r.id}`}
              className="rounded-lg border bg-[var(--color-surface)] p-4 hover:border-[var(--color-border-strong)]"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-mono text-xs text-[var(--color-ink)]">
                  {r.scenario}
                </span>
                <StatusPill status={r.status} />
              </div>
              <p className="mt-2 text-[0.82rem] leading-snug text-[var(--color-ink-muted)]">
                {copy.oneLiner}
              </p>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

function Hero() {
  return (
    <section>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--color-accent)]">
        On-call incident copilot
      </p>
      <h1 className="font-display mt-4 max-w-3xl text-[2.6rem] font-medium leading-[1.12] tracking-[-0.02em] sm:text-[3.25rem]">
        {TAGLINE}
      </h1>
      <div className="prose-col mt-6">
        {PROBLEM.map((p, i) => (
          <p key={i}>{p}</p>
        ))}
      </div>
      <div className="mt-8 flex flex-wrap gap-3">
        <Link
          to="/incidents"
          className="inline-flex items-center gap-1.5 rounded-md bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white"
        >
          See it run <ArrowRight size={15} />
        </Link>
        <Link
          to="/how-it-works"
          className="inline-flex items-center gap-1.5 rounded-md border px-4 py-2 text-sm font-medium text-[var(--color-ink)] hover:bg-[var(--color-surface-2)]"
        >
          How it works
        </Link>
      </div>
    </section>
  );
}

function TheLoop() {
  return (
    <section>
      <SectionHead
        n={1}
        kicker="The loop"
        title="Seven steps from alert to audited proposal"
        blurb="Each step is a deliberate stage in a thin, hand-written orchestration — no agent framework. The shielded steps are where a safety invariant lives."
      />
      <Figure n={1} caption="The incident loop. Hover a step for detail.">
        <LoopDiagram />
      </Figure>
    </section>
  );
}

function Architecture() {
  const cols = [
    { h: "Interfaces", items: ["CLI (built first)", "Web dashboard — REST + SSE"] },
    {
      h: "Orchestration",
      items: ["redact → triage → retrieve", "→ tool loop (sim) → synthesise", "→ guardrail → approve → record"],
      accent: true,
    },
    { h: "State — Postgres (Neon)", items: ["pgvector corpus index", "incident runs + audit", "pending approvals", "eval results"] },
  ];
  return (
    <section>
      <SectionHead
        n={2}
        kicker="Architecture"
        title="One orchestration, two front ends, all state in Postgres"
        blurb="The CLI and the dashboard call the exact same core functions. The eval suite runs that same code path. Nothing important lives on local disk."
      />
      <div className="mt-8 grid gap-3 md:grid-cols-3">
        {cols.map((c) => (
          <div
            key={c.h}
            className={`rounded-lg border p-4 ${c.accent ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]" : "bg-[var(--color-surface)]"}`}
          >
            <p className="text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-[var(--color-ink-faint)]">
              {c.h}
            </p>
            <ul className="mt-2 space-y-1 text-[0.82rem] text-[var(--color-ink-muted)]">
              {c.items.map((it) => (
                <li key={it} className="font-mono text-[0.76rem]">
                  {it}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

function Safety() {
  return (
    <section>
      <SectionHead
        n={3}
        kicker="Safety model"
        title="Six invariants, enforced in code — not requested in a prompt"
        blurb="Each is a line in the spec, checked by the eval suite. A green typecheck is not 'done' — every change runs against real behaviour."
      />
      <div className="mt-8 grid gap-3 sm:grid-cols-2">
        {SAFETY.map((s) => (
          <div key={s.id} className="rounded-lg border bg-[var(--color-surface)] p-4">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-semibold text-[var(--color-accent)]">{s.id}</span>
              <span className="text-sm font-medium text-[var(--color-ink)]">{s.title}</span>
              <span className="ml-auto">
                {s.status === "enforced" ? (
                  <span className="inline-flex items-center gap-1 text-[0.65rem] font-semibold uppercase text-[var(--color-ok)]">
                    <ShieldCheck size={12} /> enforced
                  </span>
                ) : (
                  <span className="text-[0.65rem] font-semibold uppercase text-[var(--color-ink-faint)]">
                    planned
                  </span>
                )}
              </span>
            </div>
            <p className="mt-1.5 text-[0.8rem] leading-relaxed text-[var(--color-ink-muted)]">{s.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function Evals() {
  const { data, error } = useAsync(getEvalBaseline, []);
  const m = data?.metrics;
  const tiles = m
    ? [
        ["triage accuracy", m.triage_accuracy, "≥ 0.90 target"],
        ["retrieval hit@3", m.retrieval_hit_at_3, "≥ 0.85 target", "hit-at-3"],
        ["failure-mode exact", m.failure_mode_exact, "diagnosis category"],
        ["disposition match", m.disposition_match, "auto / approve / escalate"],
        ["judge score", m.judge_mean_norm, "LLM-as-judge, 0–1", "llm-judge"],
        ["judge pass rate", m.judge_pass_rate, "fraction ≥ 3/5"],
      ]
    : [];

  return (
    <section>
      <SectionHead
        n={4}
        kicker="Evaluation"
        title="A 30-case golden set, a blessed baseline, a regression gate"
        blurb="Deterministic code gets pytest; probabilistic behaviour gets evals. The set runs the real diagnose() path and never persists. Hard safety checks must be 100%."
      />
      {error && <p className="mt-6 text-sm text-[var(--color-ink-faint)]">Baseline unavailable ({error}).</p>}
      {m && (
        <>
          <div className="mt-8 grid grid-cols-2 gap-x-6 gap-y-5 rounded-lg border bg-[var(--color-surface)] p-5 sm:grid-cols-3">
            {tiles.map(([label, val, sub, term]) => (
              <div key={label}>
                <div className="flex items-center gap-1 text-[0.62rem] font-medium uppercase tracking-[0.1em] text-[var(--color-ink-faint)]">
                  {label} {term && <Term term={term} />}
                </div>
                <div className="mt-0.5 font-mono text-xl text-[var(--color-ink)]">{val.toFixed(2)}</div>
                <div className="text-[0.7rem] text-[var(--color-ink-muted)]">{sub}</div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-[var(--color-ink-faint)]">
            Blessed {data.blessed_at?.slice(0, 10)} · {data.n_cases} cases.{" "}
            <Link to="/evals" className="text-[var(--color-accent)] hover:underline">
              Full scorecard →
            </Link>
          </p>
        </>
      )}
    </section>
  );
}

function StackAndScope() {
  return (
    <section className="grid gap-10 md:grid-cols-2">
      <div>
        <p className="text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
          Stack
        </p>
        <ul className="mt-3 space-y-2.5">
          {STACK.map(([name, note]) => (
            <li key={name} className="text-[0.85rem]">
              <span className="font-medium text-[var(--color-ink)]">{name}</span>
              <span className="text-[var(--color-ink-muted)]"> — {note}</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <p className="text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
          Non-goals (v1)
        </p>
        <ul className="mt-3 space-y-2.5">
          {NON_GOALS.map((g) => (
            <li key={g} className="flex gap-2 text-[0.85rem] text-[var(--color-ink-muted)]">
              <Minus size={15} className="mt-0.5 shrink-0 text-[var(--color-ink-faint)]" />
              {g}
            </li>
          ))}
        </ul>
        <Link
          to="/decisions"
          className="mt-4 inline-flex items-center gap-1 text-sm text-[var(--color-accent)] hover:underline"
        >
          <Check size={14} /> Read the decision log — every choice, written down
        </Link>
      </div>
    </section>
  );
}

function SectionHead({ n, kicker, title, blurb }) {
  return (
    <div className="max-w-2xl">
      <p className="flex items-center gap-2 font-mono text-[0.7rem] font-medium uppercase tracking-[0.16em] text-[var(--color-accent)]">
        {n != null && <span className="text-[var(--color-ink-faint)]">§{n}</span>}
        {kicker}
      </p>
      <h2 className="font-display mt-2 text-[1.9rem] font-medium leading-tight tracking-[-0.015em]">
        {title}
      </h2>
      {blurb && (
        <p className="mt-2.5 text-[0.95rem] leading-relaxed text-[var(--color-ink-muted)]">{blurb}</p>
      )}
    </div>
  );
}

function Figure({ n, caption, children }) {
  return (
    <figure className="mt-8">
      {children}
      <figcaption className="figcaption mt-2.5">
        Fig. {n} — {caption}
      </figcaption>
    </figure>
  );
}
