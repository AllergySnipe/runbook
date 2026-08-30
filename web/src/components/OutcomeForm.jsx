import { useState } from "react";
import { recordOutcome } from "../api.js";
import { Term } from "./ui.jsx";

const ELIGIBLE = new Set(["resolved", "escalated", "rejected"]);

// SPEC step 7: once a run is terminal, a human records what ACTUALLY turned out
// to be the root cause. That confirmed outcome becomes incident memory (ADR-0015)
// — retrieved as context on future similar alerts, never as a grounding source.
export default function OutcomeForm({ record, onRecorded }) {
  const [by, setBy] = useState("");
  const [rootCause, setRootCause] = useState("");
  const [failureMode, setFailureMode] = useState("");
  const [verdict, setVerdict] = useState(null); // true | false | null
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  if (!ELIGIBLE.has(record.status) || record.outcome) return null;

  const modelRC = record.diagnosis?.root_cause;

  const submit = async () => {
    setErr(null);
    if (!by.trim()) return setErr("Say who you are.");
    if (!rootCause.trim()) return setErr("Record what actually caused the incident.");
    setBusy(true);
    try {
      await recordOutcome(record.id, {
        by: by.trim(),
        actual_root_cause: rootCause.trim(),
        actual_failure_mode: failureMode.trim() || null,
        model_was_correct: verdict,
      });
      onRecorded();
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  };

  return (
    <section className="rounded-lg border p-4" style={{ borderColor: "var(--color-border)" }}>
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--color-ink)]">
        What actually happened? <Term term="incident-memory" />
      </h3>
      <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
        Recording the confirmed root cause files this incident in memory — the loop retrieves it
        as context the next time a similar alert fires.
      </p>

      {modelRC && (
        <p className="mt-3 rounded-md border p-2.5 text-xs text-[var(--color-ink-muted)]" style={{ borderColor: "var(--color-border)" }}>
          <span className="text-[var(--color-ink-faint)]">the run proposed:</span> {modelRC}
        </p>
      )}

      <div className="mt-3 space-y-2">
        <input
          value={by}
          onChange={(e) => setBy(e.target.value)}
          placeholder="your name"
          className="w-full rounded-md border bg-[var(--color-bg)] px-2.5 py-1.5 text-sm"
        />
        <textarea
          value={rootCause}
          onChange={(e) => setRootCause(e.target.value)}
          placeholder="the confirmed root cause"
          rows={3}
          className="w-full rounded-md border bg-[var(--color-bg)] px-2.5 py-1.5 text-sm"
        />
        <input
          value={failureMode}
          onChange={(e) => setFailureMode(e.target.value)}
          placeholder="failure_mode (optional, e.g. acquirer-gw-timeouts)"
          className="w-full rounded-md border bg-[var(--color-bg)] px-2.5 py-1.5 font-mono text-xs"
        />
      </div>

      {modelRC && (
        <div className="mt-3 flex items-center gap-2 text-xs">
          <span className="text-[var(--color-ink-faint)]">the run’s proposal was</span>
          {[
            ["right", true],
            ["wrong", false],
            ["n/a", null],
          ].map(([label, val]) => (
            <button
              key={label}
              type="button"
              onClick={() => setVerdict(val)}
              className="rounded-md border px-2 py-1"
              style={{
                borderColor: verdict === val ? "var(--color-accent)" : "var(--color-border)",
                color: verdict === val ? "var(--color-accent)" : "var(--color-ink-muted)",
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {err && <p className="mt-2 text-sm text-[var(--color-critical)]">{err}</p>}

      <button
        onClick={submit}
        disabled={busy}
        className="mt-3 rounded-md px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        style={{ background: "var(--color-accent)" }}
      >
        {busy ? "…" : "Record outcome"}
      </button>
    </section>
  );
}

// Shown once an outcome has been recorded.
export function RecordedOutcome({ outcome }) {
  if (!outcome) return null;
  const verdict =
    outcome.model_was_correct === true
      ? "the run’s proposal was confirmed right"
      : outcome.model_was_correct === false
        ? "the run’s proposal was wrong"
        : null;
  return (
    <section className="rounded-lg border p-4" style={{ borderColor: "var(--color-ok)", background: "color-mix(in oklab, var(--color-ok) 6%, transparent)" }}>
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--color-ink)]">
        Confirmed outcome <Term term="incident-memory" />
      </h3>
      <p className="mt-2 text-sm text-[var(--color-ink-muted)]">{outcome.actual_root_cause}</p>
      {outcome.actual_failure_mode && (
        <p className="mt-1 font-mono text-xs text-[var(--color-ink-faint)]">
          failure_mode: {outcome.actual_failure_mode}
        </p>
      )}
      <p className="mt-2 text-xs text-[var(--color-ink-faint)]">
        recorded by {outcome.created_by}
        {verdict ? ` · ${verdict}` : ""}
      </p>
    </section>
  );
}
