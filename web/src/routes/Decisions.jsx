import { useState } from "react";
import { ChevronDown, ExternalLink } from "lucide-react";
import { useAsync } from "../lib/useAsync.js";
import { listDecisions } from "../api.js";

const REPO_ADR = "https://github.com/AllergySnipe/runbook/blob/main/docs/adr";

export default function Decisions() {
  const { data, error, loading } = useAsync(listDecisions, []);

  return (
    <div className="space-y-10">
      <header>
        <p className="font-mono text-[0.7rem] font-medium uppercase tracking-[0.16em] text-[var(--color-accent)]">
          Decision log
        </p>
        <h1 className="font-display mt-3 text-[2.1rem] font-medium tracking-[-0.02em] sm:text-[2.6rem]">
          Every real decision, written down
        </h1>
        <p className="prose-col mt-4 text-[0.92rem] text-[var(--color-ink-muted)]">
          One architecture decision record per choice that had a genuine alternative — the context,
          the options weighed, what was picked, and the trigger that would make us revisit it. These
          are the files a reviewer reads to judge engineering judgement.
        </p>
      </header>

      {loading && <p className="text-sm text-[var(--color-ink-faint)]">Loading…</p>}
      {error && <p className="text-sm text-[var(--color-ink-faint)]">Couldn't load decisions ({error}).</p>}

      <ol className="space-y-3">
        {(data || []).map((d) => (
          <DecisionRow key={d.slug} d={d} />
        ))}
      </ol>
    </div>
  );
}

function DecisionRow({ d }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-lg border bg-[var(--color-surface)]">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <span className="font-mono text-xs text-[var(--color-ink-faint)]">
          ADR-{String(d.number).padStart(4, "0")}
        </span>
        <span className="flex-1 text-sm font-medium text-[var(--color-ink)]">{d.title}</span>
        {d.superseded_by?.length > 0 && (
          <span className="hidden text-[0.62rem] font-medium uppercase tracking-wide text-[var(--color-ink-faint)] sm:inline">
            superseded in part · ADR-{String(d.superseded_by[0]).padStart(4, "0")}
          </span>
        )}
        {d.status && (
          <span className="hidden text-[0.65rem] font-semibold uppercase tracking-wide text-[var(--color-ok)] sm:inline">
            {d.status}
          </span>
        )}
        <ChevronDown
          size={15}
          className={`shrink-0 text-[var(--color-ink-faint)] transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="border-t px-4 py-3">
          <p className="whitespace-pre-line text-[0.83rem] leading-relaxed text-[var(--color-ink-muted)]">
            {d.context}
          </p>
          <a
            href={`${REPO_ADR}/${d.slug}.md`}
            target="_blank"
            rel="noreferrer"
            className="mt-3 inline-flex items-center gap-1 text-xs text-[var(--color-accent)] hover:underline"
          >
            Full record <ExternalLink size={12} />
          </a>
        </div>
      )}
    </li>
  );
}
