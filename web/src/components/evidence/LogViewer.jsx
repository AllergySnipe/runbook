// search_logs result: { query, matches: [{ts, line, level, message}], total_scanned, hint }

const LEVEL_TONE = {
  ERROR: "--color-critical",
  WARN: "--color-warn",
  INFO: "--color-ink-muted",
  DEBUG: "--color-ink-faint",
};

export default function LogViewer({ result }) {
  const { matches = [], total_scanned, hint, query } = result;

  if (matches.length === 0) {
    return (
      <div className="rounded border border-dashed p-3 text-xs text-[var(--color-ink-muted)]">
        <span className="font-mono text-[var(--color-ink-faint)]">
          no match for “{query}” in {total_scanned} lines
        </span>
        {hint && <p className="mt-1 leading-relaxed">{hint}</p>}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded border">
      <div className="max-h-64 overflow-y-auto bg-[var(--color-bg)]">
        {matches.map((m, i) => (
          <div
            key={i}
            className="flex gap-2.5 border-b px-3 py-1 font-mono text-[0.72rem] leading-relaxed last:border-b-0"
            style={{ borderColor: "var(--color-border)" }}
          >
            <span className="shrink-0 text-[var(--color-ink-faint)]">{clock(m.ts)}</span>
            <span
              className="w-12 shrink-0 font-semibold"
              style={{ color: `var(${LEVEL_TONE[m.level] || "--color-ink-faint"})` }}
            >
              {m.level}
            </span>
            <span className="break-all text-[var(--color-ink-muted)]">{m.message || m.line}</span>
          </div>
        ))}
      </div>
      <div className="border-t bg-[var(--color-surface-2)] px-3 py-1 font-mono text-[0.68rem] text-[var(--color-ink-faint)]">
        {matches.length} shown · {total_scanned} scanned
      </div>
    </div>
  );
}

function clock(iso) {
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}
