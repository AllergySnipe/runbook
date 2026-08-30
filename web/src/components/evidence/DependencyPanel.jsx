// get_service_dependencies result:
// { service, upstreams: [{name, kind, health, note, status_url}], downstreams: [...], neighbours: [] }

const HEALTH_TONE = {
  healthy: "--color-ok",
  degraded: "--color-warn",
  down: "--color-critical",
  unknown: "--color-ink-faint",
};

export default function DependencyPanel({ result }) {
  const { service, upstreams = [], downstreams = [], neighbours = [] } = result;
  return (
    <div className="space-y-3 text-xs">
      <div className="font-mono text-[var(--color-ink)]">{service}</div>
      <Group label="upstreams" deps={upstreams} />
      <Group label="downstreams" deps={downstreams} />
      {neighbours.length > 0 && (
        <div>
          <span className="font-mono text-[0.68rem] uppercase tracking-wide text-[var(--color-ink-faint)]">
            neighbours
          </span>
          <span className="ml-2 font-mono text-[var(--color-ink-muted)]">
            {neighbours.join(", ")}
          </span>
        </div>
      )}
    </div>
  );
}

function Group({ label, deps }) {
  if (deps.length === 0) return null;
  return (
    <div>
      <span className="font-mono text-[0.68rem] uppercase tracking-wide text-[var(--color-ink-faint)]">
        {label}
      </span>
      <ul className="mt-1 space-y-1">
        {deps.map((d, i) => (
          <li key={i} className="flex flex-wrap items-baseline gap-x-2">
            <span
              className="led"
              style={{ color: `var(${HEALTH_TONE[d.health] || "--color-ink-faint"})` }}
            />
            <span className="font-mono text-[var(--color-ink)]">{d.name}</span>
            <span className="font-mono text-[var(--color-ink-faint)]">{d.kind}</span>
            <span
              className="font-mono"
              style={{ color: `var(${HEALTH_TONE[d.health] || "--color-ink-faint"})` }}
            >
              {d.health}
            </span>
            {d.note && <span className="text-[var(--color-ink-muted)]">— {d.note}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
