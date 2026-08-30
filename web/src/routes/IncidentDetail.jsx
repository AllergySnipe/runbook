import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getIncident, openEventStream } from "../api.js";
import { buildTimeline, isTerminal } from "../lib/timeline.js";
import { StatusPill, fmtTime } from "../lib/format.jsx";
import Proposal from "../components/Proposal.jsx";
import ApprovalForm from "../components/ApprovalForm.jsx";

export default function IncidentDetail() {
  const { id } = useParams();
  const [rec, setRec] = useState(null); // persisted RunRecord once finished
  const [live, setLive] = useState(null); // { scenario, alert, events } while running
  const [err, setErr] = useState(null);
  const closeRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const data = await getIncident(id);
      if (data.status === "running") {
        setLive({ scenario: data.scenario, alert: data.alert, events: data.events || [] });
      } else {
        setRec(data);
        setLive(null);
      }
    } catch (e) {
      setErr(e.message);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  // While running, stream progress. On a terminal event, re-load the record.
  useEffect(() => {
    if (!live || rec) return;
    closeRef.current = openEventStream(id, ({ type, data }) => {
      setLive((prev) => {
        if (!prev) return prev;
        const events = [...prev.events, { type, data }];
        if (isTerminal(events)) setTimeout(load, 150);
        return { ...prev, events };
      });
    });
    return () => closeRef.current?.();
  }, [id, live, rec, load]);

  if (err) return <Problem id={id} msg={err} />;
  if (!rec && !live) return <p className="text-sm text-zinc-500">Loading…</p>;

  const scenario = rec?.scenario || live?.scenario;
  const status = rec?.status || "running";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Link to="/" className="text-xs text-zinc-500 hover:text-zinc-300">
            ← all incidents
          </Link>
          <h1 className="mt-1 font-mono text-lg text-zinc-100">{scenario}</h1>
          <p className="text-xs text-zinc-500">
            {id}
            {rec && ` · ${fmtTime(rec.created_at)}`}
          </p>
        </div>
        <StatusPill status={status} />
      </div>

      <section className="rounded-lg border border-zinc-800 p-4">
        <p className="text-xs font-semibold text-zinc-500">ALERT</p>
        <p className="mt-1 text-sm text-zinc-300">{rec?.alert || live?.alert}</p>
      </section>

      {live && !rec && <LiveTimeline events={live.events} />}

      {rec && (
        <>
          <Proposal record={rec} />
          {rec.status === "awaiting-approval" && (
            <ApprovalForm record={rec} onResolved={setRec} />
          )}
        </>
      )}
    </div>
  );
}

function LiveTimeline({ events }) {
  const items = buildTimeline(events);
  const toneCls = {
    tool: "text-sky-300",
    warn: "text-amber-300",
    error: "text-rose-400",
    strong: "text-zinc-100 font-medium",
    muted: "text-zinc-500",
  };
  return (
    <section className="rounded-lg border border-zinc-800 p-4">
      <p className="mb-3 text-xs font-semibold text-zinc-500">PROGRESS</p>
      <ol className="space-y-1.5">
        {items.map((it, i) => (
          <li key={i} className={`flex items-center gap-2 text-sm ${toneCls[it.tone] || "text-zinc-300"}`}>
            <span className={it.pending ? "animate-pulse" : ""}>{it.pending ? "○" : "●"}</span>
            {it.label}
          </li>
        ))}
        {items.length === 0 && <li className="text-sm text-zinc-500">Waiting for the loop…</li>}
      </ol>
    </section>
  );
}

function Problem({ id, msg }) {
  return (
    <div className="space-y-3">
      <Link to="/" className="text-xs text-zinc-500 hover:text-zinc-300">
        ← all incidents
      </Link>
      <p className="text-sm text-rose-400">
        {id}: {msg}
      </p>
    </div>
  );
}
