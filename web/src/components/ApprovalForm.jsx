import { useState } from "react";
import { decide } from "../api.js";
import { Term } from "./ui.jsx";

// SPEC steps 6 + 7: a human approves or rejects the state-changing steps and
// records the actual root cause on the way through.
export default function ApprovalForm({ record, onResolved }) {
  const [by, setBy] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);

  const pending = (record.approvals || []).filter((a) => a.state === "pending");

  const act = async (decision) => {
    setErr(null);
    if (!by.trim()) return setErr("Say who you are.");
    if (decision === "reject" && !note.trim()) return setErr("A note is required to reject.");
    setBusy(decision);
    try {
      const updated = await decide(record.id, decision, { by: by.trim(), note: note.trim() || null });
      onResolved(updated);
    } catch (e) {
      setErr(e.message);
      setBusy(null);
    }
  };

  return (
    <section
      className="rounded-lg border p-4"
      style={{ borderColor: "var(--color-warn)", background: "color-mix(in oklab, var(--color-warn) 7%, transparent)" }}
    >
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--color-ink)]">
        {pending.length} state-changing step(s) need a decision <Term term="approval-gate" />
      </h3>
      <ul className="mt-2 space-y-1 text-xs text-[var(--color-ink-muted)]">
        {pending.map((a) => (
          <li key={a.id}>
            step {a.step_index + 1}: {a.action}
          </li>
        ))}
      </ul>

      <div className="mt-3 space-y-2">
        <input
          value={by}
          onChange={(e) => setBy(e.target.value)}
          placeholder="your name"
          className="w-full rounded-md border bg-[var(--color-bg)] px-2.5 py-1.5 text-sm"
        />
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="root-cause note / reason (required to reject)"
          rows={2}
          className="w-full rounded-md border bg-[var(--color-bg)] px-2.5 py-1.5 text-sm"
        />
      </div>

      {err && <p className="mt-2 text-sm text-[var(--color-critical)]">{err}</p>}

      <div className="mt-3 flex gap-2">
        <button
          onClick={() => act("approve")}
          disabled={busy}
          className="rounded-md px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          style={{ background: "var(--color-ok)" }}
        >
          {busy === "approve" ? "…" : "Approve all"}
        </button>
        <button
          onClick={() => act("reject")}
          disabled={busy}
          className="rounded-md px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          style={{ background: "var(--color-critical)" }}
        >
          {busy === "reject" ? "…" : "Reject run"}
        </button>
      </div>
    </section>
  );
}
