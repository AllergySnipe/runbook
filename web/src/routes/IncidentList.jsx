import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listIncidents, listScenarios, startIncident } from "../api.js";
import { StatusPill, fmtTime } from "../lib/format.jsx";

export default function IncidentList() {
  const [rows, setRows] = useState([]);
  const [err, setErr] = useState(null);

  const refresh = () => listIncidents().then(setRows).catch((e) => setErr(e.message));

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000); // cheap poll keeps the list fresh
    return () => clearInterval(t);
  }, []);

  return (
    <div className="space-y-8">
      <NewIncident onStarted={refresh} />

      {err && <p className="text-sm text-rose-400">{err}</p>}

      <div>
        <h2 className="mb-3 text-sm font-semibold text-zinc-400">Recent incidents</h2>
        <ul className="divide-y divide-zinc-800 rounded-lg border border-zinc-800">
          {rows.length === 0 && (
            <li className="px-4 py-6 text-sm text-zinc-500">No runs yet.</li>
          )}
          {rows.map((r) => (
            <li key={r.id}>
              <Link
                to={`/incidents/${r.id}`}
                className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-zinc-900"
              >
                <div className="min-w-0">
                  <div className="truncate font-mono text-sm text-zinc-200">{r.scenario}</div>
                  <div className="text-xs text-zinc-500">
                    {r.id} · {fmtTime(r.created_at)}
                  </div>
                </div>
                <StatusPill status={r.status} />
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function NewIncident({ onStarted }) {
  const nav = useNavigate();
  const [scenarios, setScenarios] = useState([]);
  const [scenario, setScenario] = useState("");
  const [alert, setAlert] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    listScenarios()
      .then((s) => {
        setScenarios(s);
        setScenario(s[0]?.name || "");
      })
      .catch((e) => setErr(e.message));
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const { id } = await startIncident({ scenario, alert: alert.trim() || null });
      onStarted?.();
      nav(`/incidents/${id}`);
    } catch (e2) {
      setErr(e2.message);
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3 rounded-lg border border-zinc-800 p-4">
      <h2 className="text-sm font-semibold text-zinc-300">Run an incident</h2>
      <div className="flex flex-wrap gap-3">
        <select
          value={scenario}
          onChange={(e) => setScenario(e.target.value)}
          className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm"
        >
          {scenarios.map((s) => (
            <option key={s.name} value={s.name}>
              {s.name}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={busy || !scenario}
          className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? "Starting…" : "Start"}
        </button>
      </div>
      <input
        value={alert}
        onChange={(e) => setAlert(e.target.value)}
        placeholder="Optional: override the alert text (default: the scenario's own alert)"
        className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm placeholder:text-zinc-600"
      />
      {err && <p className="text-sm text-rose-400">{err}</p>}
    </form>
  );
}
