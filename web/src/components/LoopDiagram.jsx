import { useState } from "react";
import { ChevronRight, ShieldCheck } from "lucide-react";
import { LOOP_STEPS } from "../content/copy.js";

// The seven-step loop as an interactive pipeline. Click a step to pin its
// detail; hover to preview. Safety-bearing steps carry a shield.
export default function LoopDiagram({ activeKey, onStep }) {
  const [hover, setHover] = useState(null);
  const shown = hover || activeKey || null;
  const detail = LOOP_STEPS.find((s) => s.key === shown);

  return (
    <div>
      <ol className="flex flex-wrap items-stretch gap-1.5">
        {LOOP_STEPS.map((s, i) => {
          const on = s.key === shown;
          return (
            <li key={s.key} className="flex items-stretch">
              <button
                type="button"
                onMouseEnter={() => setHover(s.key)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(s.key)}
                onBlur={() => setHover(null)}
                onClick={() => onStep?.(s.key)}
                className={`group flex min-w-[7.5rem] flex-col rounded-lg border px-3 py-2 text-left transition-colors ${
                  on
                    ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
                    : "bg-[var(--color-surface)] hover:border-[var(--color-border-strong)]"
                }`}
              >
                <span className="flex items-center gap-1 text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-[var(--color-ink-faint)]">
                  {String(s.n).padStart(2, "0")}
                  {s.safety && <ShieldCheck size={11} className="text-[var(--color-accent)]" />}
                </span>
                <span className="mt-0.5 text-sm font-medium text-[var(--color-ink)]">{s.title}</span>
                <span className="mt-0.5 text-[0.72rem] leading-snug text-[var(--color-ink-muted)]">
                  {s.short}
                </span>
              </button>
              {i < LOOP_STEPS.length - 1 && (
                <ChevronRight
                  size={14}
                  className="mx-0.5 shrink-0 self-center text-[var(--color-ink-faint)]"
                />
              )}
            </li>
          );
        })}
      </ol>

      {detail && (
        <div className="mt-3 rounded-lg border bg-[var(--color-surface-2)] p-4">
          <div className="mb-1 flex items-center gap-2">
            <span className="text-sm font-semibold text-[var(--color-ink)]">
              {detail.n}. {detail.title}
            </span>
            {detail.safety && (
              <span className="inline-flex items-center gap-1 rounded bg-[var(--color-accent-soft)] px-1.5 py-0.5 text-[0.65rem] font-semibold text-[var(--color-accent)]">
                <ShieldCheck size={11} /> {detail.safety}
              </span>
            )}
          </div>
          <p className="text-[0.82rem] leading-relaxed text-[var(--color-ink-muted)]">{detail.body}</p>
        </div>
      )}
    </div>
  );
}
