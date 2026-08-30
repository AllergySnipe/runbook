import { useState } from "react";
import { ChevronRight, ExternalLink } from "lucide-react";
import { getRunbook } from "../../api.js";

const REPO_BLOB = "https://github.com/AllergySnipe/runbook/blob/main";

// Given a remediation step's runbook_quote and the retrieved runbook path, show
// the quote highlighted *in context* in the real runbook — so it's visibly
// lifted from a procedure, not invented. Matches the way core/loop.py checks
// grounding: exact substring first, then a normalised fragment fallback.
export default function RunbookQuote({ quote, path }) {
  const [open, setOpen] = useState(false);
  const [doc, setDoc] = useState(null);
  const [err, setErr] = useState(null);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && doc == null && !err && path) {
      try {
        const { markdown } = await getRunbook(path);
        setDoc(markdown);
      } catch (e) {
        setErr(e.message);
      }
    }
  };

  return (
    <div>
      <button
        type="button"
        onClick={toggle}
        className="flex items-start gap-1.5 text-left font-mono text-[0.72rem] leading-relaxed text-[var(--color-ink-faint)] hover:text-[var(--color-ink-muted)]"
      >
        <ChevronRight
          size={11}
          className={`mt-0.5 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="border-l-2 border-[var(--color-border-strong)] pl-2">{quote}</span>
      </button>

      {open && (
        <div className="mt-2">
          {err && <p className="font-mono text-[0.7rem] text-[var(--color-ink-faint)]">{err}</p>}
          {doc && <Excerpt markdown={doc} quote={quote} />}
          {path && (
            <a
              href={`${REPO_BLOB}/${path}`}
              target="_blank"
              rel="noreferrer"
              className="mt-1.5 inline-flex items-center gap-1 font-mono text-[0.68rem] text-[var(--color-accent)] hover:underline"
            >
              {path} <ExternalLink size={10} />
            </a>
          )}
        </div>
      )}
    </div>
  );
}

const norm = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

function Excerpt({ markdown, quote }) {
  const lines = markdown.split("\n");

  // 1. exact (case-insensitive) span within a line
  let hitLine = lines.findIndex((l) => l.toLowerCase().includes(quote.trim().toLowerCase()));
  let mode = "exact";

  // 2. normalised fragment fallback
  if (hitLine < 0) {
    const frag = norm(quote).slice(0, 55);
    hitLine = lines.findIndex((l) => norm(l).includes(frag));
    mode = "fuzzy";
  }

  if (hitLine < 0) {
    return (
      <pre className="max-h-56 overflow-auto rounded border bg-[var(--color-bg)] p-2.5 font-mono text-[0.7rem] leading-relaxed text-[var(--color-ink-muted)]">
        {markdown.slice(0, 1200)}
      </pre>
    );
  }

  const from = Math.max(0, hitLine - 3);
  const to = Math.min(lines.length, hitLine + 4);

  return (
    <pre className="max-h-64 overflow-auto rounded border bg-[var(--color-bg)] p-2.5 font-mono text-[0.7rem] leading-relaxed">
      {lines.slice(from, to).map((l, i) => {
        const isHit = from + i === hitLine;
        return (
          <div key={i} className={isHit ? "" : "text-[var(--color-ink-faint)]"}>
            {isHit ? highlight(l, quote, mode) : l || " "}
          </div>
        );
      })}
    </pre>
  );
}

function highlight(line, quote, mode) {
  if (mode === "exact") {
    const lo = line.toLowerCase().indexOf(quote.trim().toLowerCase());
    if (lo >= 0) {
      const end = lo + quote.trim().length;
      return (
        <>
          <span className="text-[var(--color-ink-muted)]">{line.slice(0, lo)}</span>
          <mark className="rounded bg-[var(--color-accent-soft)] px-0.5 text-[var(--color-ink)]">
            {line.slice(lo, end)}
          </mark>
          <span className="text-[var(--color-ink-muted)]">{line.slice(end)}</span>
        </>
      );
    }
  }
  return (
    <mark className="rounded bg-[var(--color-accent-soft)] px-0.5 text-[var(--color-ink)]">
      {line}
    </mark>
  );
}
