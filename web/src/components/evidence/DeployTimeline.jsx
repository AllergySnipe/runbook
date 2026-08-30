import { Database } from "lucide-react";

// get_recent_deploys result: { deploys: [{at, version, change, service, migration, migrations}], service }

export default function DeployTimeline({ result }) {
  const deploys = result.deploys || [];
  if (deploys.length === 0) {
    return (
      <p className="rounded border border-dashed p-3 font-mono text-xs text-[var(--color-ink-faint)]">
        no deploys in window
      </p>
    );
  }
  return (
    <ol className="relative space-y-3 border-l pl-4" style={{ borderColor: "var(--color-border-strong)" }}>
      {deploys.map((d, i) => (
        <li key={i} className="relative">
          <span
            className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full"
            style={{ background: d.migration ? "var(--color-serious)" : "var(--color-ink-faint)" }}
          />
          <div className="flex flex-wrap items-baseline gap-x-2 font-mono text-xs">
            <span className="text-[var(--color-ink-faint)]">{stamp(d.at)}</span>
            <span className="text-[var(--color-ink)]">{d.service}</span>
            <span className="text-[var(--color-ink-muted)]">{d.version}</span>
            {d.migration && (
              <span className="inline-flex items-center gap-1 text-[var(--color-serious)]">
                <Database size={11} /> migration
                {d.migrations?.length ? ` · ${d.migrations.join(", ")}` : ""}
              </span>
            )}
          </div>
          <p className="mt-0.5 text-[0.78rem] text-[var(--color-ink-muted)]">{d.change}</p>
        </li>
      ))}
    </ol>
  );
}

function stamp(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
