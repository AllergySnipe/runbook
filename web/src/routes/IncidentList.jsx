import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Play, ChevronDown, Loader2 } from "lucide-react";
import { StatusPill, Badge, Term, Panel } from "../components/ui.jsx";
import { listIncidents, listScenarios, startIncident } from "../api.js";
import { fmtTime, SEVERITY_TONE } from "../lib/format.js";
import { SCENARIO_COPY } from "../content/scenarios.js";

const STATUSES = ["awaiting-approval", "resolved", "rejected", "escalated", "short-circuited"];

export default function IncidentList() {
  const [rows, setRows] = useState([]);
  const [filter, setFilter] = useState(null);
  const [err, setErr] = useState(null);

  const refresh = () => listIncidents().then(setRows).catch((e) => setErr(e.message));
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, []);

  const shown = filter ? rows.filter((r) => r.status === filter) : rows;

  return (
    <div className="space-y-10">
      <header>
        <h1 className="font-mono text-xl text-[var(--color-ink)]">incidents</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[var(--color-ink-muted)]">
          Start a run against one of the modelled <Term term="failure-mode">failure modes</Term> and
          watch the loop work in real time, or open a past run to inspect its full audit record.
        </p>
      </header>

      <Launcher onStarted={refresh} />

      <section>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="font-mono text-[0.68rem] font-medium uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
            recent runs
          </h2>
          <div className="flex flex-wrap gap-1">
            <FilterChip active={!filter} onClick={() => setFilter(null)}>
              all
            </FilterChip>
            {STATUSES.map((s) => (
              <FilterChip key={s} active={filter === s} onClick={() => setFilter(s)}>
                {s}
              </FilterChip>
            ))}
          </div>
        </div>

        {err && <p className="font-mono text-sm text-[var(--color-critical)]">{err}</p>}

        <Panel bodyClass="p-0">
          <ul className="divide-y" style={{ borderColor: "var(--color-border)" }}>
            {shown.length === 0 && (
              <li className="px-4 py-8 text-center font-mono text-sm text-[var(--color-ink-faint)]">
                no runs{filter ? ` · ${filter}` : ""}
              </li>
            )}
            {shown.map((r) => {
              const copy = SCENARIO_COPY[r.scenario];
              return (
                <li key={r.id}>
                  <Link
                    to={`/incidents/${r.id}`}
                    className="flex items-center gap-4 px-4 py-2.5 hover:bg-[var(--color-surface-2)]"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate font-mono text-[0.82rem] text-[var(--color-ink)]">
                          {r.scenario}
                        </span>
                        {r.disposition && (
                          <Badge tone={r.disposition === "escalate" ? "serious" : "neutral"}>
                            {r.disposition}
                          </Badge>
                        )}
                      </div>
                      {copy && (
                        <p className="mt-0.5 truncate text-xs text-[var(--color-ink-muted)]">
                          {copy.oneLiner}
                        </p>
                      )}
                    </div>
                    <span className="hidden shrink-0 font-mono text-[0.7rem] text-[var(--color-ink-faint)] sm:block">
                      {fmtTime(r.created_at)}
                    </span>
                    <StatusPill status={r.status} />
                  </Link>
                </li>
              );
            })}
          </ul>
        </Panel>
      </section>
    </div>
  );
}

function FilterChip({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded px-2 py-0.5 font-mono text-[0.7rem] transition-colors ${
        active
          ? "bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
          : "text-[var(--color-ink-faint)] hover:text-[var(--color-ink)]"
      }`}
    >
      {children}
    </button>
  );
}

function Launcher({ onStarted }) {
  const [scenarios, setScenarios] = useState([]);
  const [err, setErr] = useState(null);

  useEffect(() => {
    listScenarios()
      .then((s) => setScenarios(s.filter((x) => x.name !== "healthy").concat(s.filter((x) => x.name === "healthy"))))
      .catch((e) => setErr(e.message));
  }, []);

  return (
    <section>
      <h2 className="mb-3 font-mono text-[0.68rem] font-medium uppercase tracking-[0.14em] text-[var(--color-ink-faint)]">
        run an incident
      </h2>
      {err && <p className="font-mono text-sm text-[var(--color-critical)]">{err}</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        {scenarios.map((s) => (
          <ScenarioCard key={s.name} scenario={s} onStarted={onStarted} />
        ))}
      </div>
    </section>
  );
}

function ScenarioCard({ scenario, onStarted }) {
  const nav = useNavigate();
  const copy = SCENARIO_COPY[scenario.name] || {};
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState(false);
  const [alertText, setAlertText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const body = { scenario: scenario.name };
      if (custom && alertText.trim()) body.alert = alertText.trim();
      const { id } = await startIncident(body);
      onStarted?.();
      nav(`/incidents/${id}`);
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  };

  const sampleAlert = JSON.stringify(
    {
      status: "firing",
      labels: { alertname: scenario.alert || "PaymentsvcIncident", service: "paymentsvc", severity: "critical" },
      annotations: { summary: (copy.oneLiner || scenario.summary || "").slice(0, 160) },
      startsAt: new Date().toISOString(),
    },
    null,
    2,
  );

  return (
    <div className="flex flex-col rounded-lg border bg-[var(--color-surface)] p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-[var(--color-ink)]">{scenario.name}</span>
            {scenario.severity && (
              <Badge tone={SEVERITY_TONE[scenario.severity] || "neutral"}>{scenario.severity}</Badge>
            )}
          </div>
          <p className="mt-1 text-[0.82rem] leading-snug text-[var(--color-ink-muted)]">
            {copy.oneLiner || scenario.summary}
          </p>
        </div>
      </div>

      {open && (
        <div className="mt-3 space-y-3 border-t pt-3">
          <dl className="space-y-2 text-[0.78rem]">
            <Detail term="Business impact" value={copy.impact} />
            <Detail term="What a good investigation finds" value={copy.watch} />
            <Detail term="Why it's tricky" value={copy.difficulty} />
            {scenario.expected_runbook && (
              <Detail
                term="Expected runbook"
                value={<span className="font-mono">{scenario.expected_runbook}</span>}
              />
            )}
          </dl>

          <div className="rounded-md border bg-[var(--color-bg)] p-2.5">
            <label className="flex cursor-pointer items-center gap-2 text-[0.75rem] text-[var(--color-ink-muted)]">
              <input
                type="checkbox"
                checked={custom}
                onChange={(e) => setCustom(e.target.checked)}
                className="accent-[var(--color-accent)]"
              />
              Paste a custom alert (Alertmanager JSON or free text)
            </label>
            {custom && (
              <>
                <p className="mt-2 text-[0.7rem] leading-relaxed text-[var(--color-ink-faint)]">
                  This scenario's sim is still the environment the agent investigates. Your text is
                  what it <span className="term">triages</span> and reasons over — swap it for a real
                  Alertmanager payload to see triage + the loop handle it.
                </p>
                <textarea
                  value={alertText}
                  onChange={(e) => setAlertText(e.target.value)}
                  rows={6}
                  placeholder={sampleAlert}
                  className="mt-2 w-full rounded border bg-[var(--color-surface)] p-2 font-mono text-[0.7rem] leading-relaxed placeholder:text-[var(--color-ink-faint)]"
                />
                <button
                  type="button"
                  onClick={() => setAlertText(sampleAlert)}
                  className="mt-1 text-[0.68rem] text-[var(--color-accent)] hover:underline"
                >
                  Fill with a sample payload
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {err && <p className="mt-2 text-xs text-[var(--color-critical)]">{err}</p>}

      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={run}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-md bg-[var(--color-accent)] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
        >
          {busy ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          {busy ? "Starting…" : custom && alertText.trim() ? "Run with this alert" : "Run this incident"}
        </button>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="inline-flex items-center gap-1 text-xs text-[var(--color-ink-faint)] hover:text-[var(--color-ink)]"
        >
          {open ? "Less" : "Details & custom alert"}
          <ChevronDown size={13} className={open ? "rotate-180" : ""} />
        </button>
      </div>
    </div>
  );
}

function Detail({ term, value }) {
  if (!value) return null;
  return (
    <div>
      <dt className="font-medium text-[var(--color-ink-faint)]">{term}</dt>
      <dd className="mt-0.5 leading-relaxed text-[var(--color-ink-muted)]">{value}</dd>
    </div>
  );
}
