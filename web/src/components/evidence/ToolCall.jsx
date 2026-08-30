import { useState } from "react";
import { ChevronRight, Lock, AlertTriangle } from "lucide-react";
import MetricChart from "./MetricChart.jsx";
import LogViewer from "./LogViewer.jsx";
import DeployTimeline from "./DeployTimeline.jsx";
import DependencyPanel from "./DependencyPanel.jsx";

const GLOSS = {
  query_metrics: (a) => `Checked ${a.metric || "a metric"}`,
  search_logs: (a) => `Searched logs for “${a.query ?? ""}”`,
  get_recent_deploys: (a) =>
    a.service ? `Pulled ${a.service} deploy history` : "Pulled the deploy history",
  get_service_dependencies: () => "Checked the dependency graph",
};

export default function ToolCall({ call, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const { name, input = {}, is_error, result } = call;
  const why = (GLOSS[name] || (() => name))(input);
  const args = Object.entries(input)
    .map(([k, v]) => `${k}=${v}`)
    .join("  ");

  return (
    <div className="rounded border">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <ChevronRight
          size={13}
          className={`shrink-0 text-[var(--color-ink-faint)] transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="font-mono text-[0.8rem] text-[var(--color-accent)]">{name}</span>
        <span className="truncate text-xs text-[var(--color-ink-muted)]">{why}</span>
        <span className="ml-auto flex shrink-0 items-center gap-2">
          {is_error && <AlertTriangle size={12} className="text-[var(--color-critical)]" />}
          <span
            className="hidden items-center gap-1 font-mono text-[0.62rem] uppercase text-[var(--color-ink-faint)] sm:inline-flex"
            title="On the read-only allowlist — SPEC S2"
          >
            <Lock size={10} /> read-only
          </span>
        </span>
      </button>

      {open && (
        <div className="space-y-3 border-t px-3 py-3">
          {args && (
            <div className="font-mono text-[0.7rem] text-[var(--color-ink-faint)]">{args}</div>
          )}
          <Evidence name={name} result={result} isError={is_error} />
        </div>
      )}
    </div>
  );
}

function Evidence({ name, result, isError }) {
  if (isError || result == null) {
    return (
      <pre className="overflow-x-auto rounded bg-[var(--color-bg)] p-2 font-mono text-[0.7rem] text-[var(--color-critical)]">
        {typeof result === "string" ? result : JSON.stringify(result, null, 2)}
      </pre>
    );
  }
  if (name === "query_metrics") {
    if (result.error) {
      return (
        <p className="font-mono text-xs text-[var(--color-warn)]">
          {result.error}
          {result.available?.length ? ` · available: ${result.available.join(", ")}` : ""}
        </p>
      );
    }
    return <MetricChart series={result.series || []} />;
  }
  if (name === "search_logs") return <LogViewer result={result} />;
  if (name === "get_recent_deploys") return <DeployTimeline result={result} />;
  if (name === "get_service_dependencies") return <DependencyPanel result={result} />;
  return (
    <pre className="overflow-x-auto rounded bg-[var(--color-bg)] p-2 font-mono text-[0.7rem] text-[var(--color-ink-muted)]">
      {JSON.stringify(result, null, 2)}
    </pre>
  );
}
