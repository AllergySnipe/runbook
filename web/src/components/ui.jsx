import { useId, useState } from "react";
import { Info } from "lucide-react";
import { GLOSSARY } from "../content/glossary.js";

// ── Card ────────────────────────────────────────────────────────────────────
export function Card({ children, className = "", as: As = "div", ...rest }) {
  return (
    <As
      className={`rounded-[var(--radius-card)] border bg-[var(--color-surface)] ${className}`}
      {...rest}
    >
      {children}
    </As>
  );
}

// ── Panel — a bordered "terminal window" with an optional header bar ─────────
export function Panel({ title, right, children, className = "", bodyClass = "p-4" }) {
  return (
    <div className={`panel ${className}`}>
      {(title || right) && (
        <div className="panel-bar">
          {title}
          {right && <span className="ml-auto normal-case tracking-normal">{right}</span>}
        </div>
      )}
      <div className={bodyClass}>{children}</div>
    </div>
  );
}

// ── Section: a labelled block ──────────────────────────────────────────────
export function Section({ label, hint, right, children, className = "" }) {
  return (
    <section className={className}>
      {label && (
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <h3 className="flex items-center gap-1 font-mono text-[0.68rem] font-medium uppercase tracking-[0.12em] text-[var(--color-ink-faint)]">
            {label}
            {hint && <Term term={hint} />}
          </h3>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Label({ children, hint }) {
  return (
    <h3 className="mb-1.5 flex items-center gap-1 font-mono text-[0.68rem] font-medium uppercase tracking-[0.13em] text-[var(--color-ink-faint)]">
      {children}
      {hint && <Term term={hint} />}
    </h3>
  );
}

// ── Status LED + label ─────────────────────────────────────────────────────
const STATUS_TOKENS = {
  running: ["--color-info", "running"],
  "awaiting-approval": ["--color-warn", "awaiting approval"],
  resolved: ["--color-ok", "resolved"],
  rejected: ["--color-critical", "rejected"],
  escalated: ["--color-serious", "escalated"],
  "short-circuited": ["--color-ink-faint", "short-circuited"],
};

export function StatusPill({ status }) {
  const [tok, label] = STATUS_TOKENS[status] || ["--color-ink-faint", status];
  return (
    <span
      className="inline-flex items-center gap-2 font-mono text-xs"
      style={{ color: `var(${tok})` }}
    >
      <span className={`led ${status === "running" ? "dot-pending" : ""}`} />
      {label}
    </span>
  );
}

export function LED({ tone = "--color-ink-faint", pulse = false }) {
  return <span className={`led ${pulse ? "dot-pending" : ""}`} style={{ color: `var(${tone})` }} />;
}

export function Badge({ children, tone = "neutral" }) {
  const tok =
    {
      ok: "--color-ok",
      warn: "--color-warn",
      serious: "--color-serious",
      critical: "--color-critical",
      accent: "--color-accent",
    }[tone] || "--color-ink-faint";
  return (
    <span
      className="inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[0.62rem] font-semibold uppercase tracking-wide"
      style={{
        color: `var(${tok})`,
        background: `color-mix(in oklab, var(${tok}) 12%, transparent)`,
      }}
    >
      {children}
    </span>
  );
}

// ── Stat: one number with a label ─────────────────────────────────────────
export function Stat({ label, value, sub, term }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1 font-mono text-[0.62rem] font-medium uppercase tracking-[0.12em] text-[var(--color-ink-faint)]">
        {label}
        {term && <Term term={term} />}
      </div>
      <div className="mt-0.5 font-mono text-lg text-[var(--color-ink)]">{value}</div>
      {sub && <div className="font-mono text-[0.7rem] text-[var(--color-ink-muted)]">{sub}</div>}
    </div>
  );
}

export function StatRow({ children }) {
  return (
    <div className="panel flex flex-wrap gap-x-8 gap-y-4 px-4 py-3">{children}</div>
  );
}

// ── Term: inline glossary ─────────────────────────────────────────────────
export function Term({ term, children, className = "" }) {
  const entry = typeof term === "string" ? GLOSSARY[term] : term;
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!entry) return children ? <span className={className}>{children}</span> : null;

  return (
    <span
      className={`relative inline-block ${className}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children ? (
        <span className="term" tabIndex={0} aria-describedby={open ? id : undefined}>
          {children}
        </span>
      ) : (
        <button
          type="button"
          aria-label={`Define: ${entry.title}`}
          aria-describedby={open ? id : undefined}
          className="align-middle text-[var(--color-ink-faint)] hover:text-[var(--color-accent)]"
        >
          <Info size={12} strokeWidth={2} />
        </button>
      )}
      {open && (
        <span
          id={id}
          role="tooltip"
          className="absolute bottom-full left-1/2 z-50 mb-2 w-72 -translate-x-1/2 rounded-lg border bg-[var(--color-surface-2)] p-3 text-left text-xs font-normal leading-relaxed text-[var(--color-ink-muted)] shadow-xl"
          style={{ borderColor: "var(--color-border-strong)" }}
        >
          <span className="mb-1 block font-semibold text-[var(--color-ink)]">{entry.title}</span>
          {entry.body}
        </span>
      )}
    </span>
  );
}

export function Divider({ className = "" }) {
  return (
    <hr className={`border-0 border-t ${className}`} style={{ borderColor: "var(--color-border)" }} />
  );
}
