import { useState } from "react";
import { decide } from "../api.js";

// SPEC step 6 + 7: a human approves or rejects the state-changing steps, and can
// record the actual root cause on the way through. Whole-run decisions here;
// per-step is a CLI-only nicety for now.
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
      const updated = await decide(record.id, decision, {
        by: by.trim(),
        note: note.trim() || null,
      });
      onResolved(updated);
    } catch (e) {
      setErr(e.message);
      setBusy(null);
    }
  };

  return (
    <section className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
      <h3 className="text-sm font-semibold text-amber-200">
        {pending.length} state-changing step(s) need a decision
      </h3>
      <ul className="mt-2 space-y-1 text-xs text-zinc-300">
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
          className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm"
        />
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="root-cause note / reason (required to reject)"
          rows={2}
          className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm"
        />
      </div>

      {err && <p className="mt-2 text-sm text-rose-400">{err}</p>}

      <div className="mt-3 flex gap-2">
        <button
          onClick={() => act("approve")}
          disabled={busy}
          className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy === "approve" ? "…" : "Approve all"}
        </button>
        <button
          onClick={() => act("reject")}
          disabled={busy}
          className="rounded bg-rose-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy === "reject" ? "…" : "Reject run"}
        </button>
      </div>
    </section>
  );
}
