import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, X } from "lucide-react";
import { getIncident, openEventStream } from "../api.js";
import { buildTimeline, eventKey, isTerminal, fmtElapsed } from "../lib/timeline.js";
import { fmtTime, fmtDuration, fmtTokens } from "../lib/format.js";
import { StatusPill, Stat, StatRow, Term, Panel } from "../components/ui.jsx";
import { SCENARIO_COPY } from "../content/scenarios.js";
import Proposal from "../components/Proposal.jsx";
import ApprovalForm from "../components/ApprovalForm.jsx";

export default function IncidentDetail() {
  const { id } = useParams();
  const [rec, setRec] = useState(null);
  const [meta, setMeta] = useState(null);
  const [events, setEvents] = useState([]);
  const [phase, setPhase] = useState("loading");
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = await getIncident(id);
      if (data.status === "running") {
        setMeta({ scenario: data.scenario, alert: data.alert });
        setEvents(seed(data.events || []));
        setPhase("running");
      } else {
        setRec(data);
        setPhase("done");
      }
    } catch (e) {
      setErr(e.message);
      setPhase("error");
    }
  }, [id]);

  useEffect(() => {
    setRec(null);
    setMeta(null);
    setEvents([]);
    setPhase("loading");
    setErr(null);
    load();
  }, [id, load]);

  useEffect(() => {
    if (phase !== "running") return;
    let closed = false;
    const close = openEventStream(id, ({ type, data }) => {
      setEvents((prev) => {
        const key = eventKey({ type, data });
        if (prev.some((e) => eventKey(e) === key)) return prev;
        const next = [...prev, { type, data, t: Date.now() }];
        if (!closed && (type === "finished" || type === "error")) {
          closed = true;
          setTimeout(load, 250);
        }
        return next;
      });
    });
    return close;
  }, [id, phase, load]);

  const scenario = rec?.scenario || meta?.scenario;
  const copy = scenario ? SCENARIO_COPY[scenario] : null;
  const streaming = phase === "running" && !isTerminal(events);

  return (
    <div className="space-y-6">
      <Link
        to="/incidents"
        className="inline-flex items-center gap-1 font-mono text-[0.7rem] uppercase tracking-wide text-[var(--color-ink-faint)] hover:text-[var(--color-ink)]"
      >
        <ArrowLeft size={12} /> incidents
      </Link>

      {phase === "error" && (
        <p className="font-mono text-sm text-[var(--color-critical)]">
          {id}: {err}
        </p>
      )}
      {phase === "loading" && (
        <p className="font-mono text-sm text-[var(--color-ink-faint)] cursor-blink">loading</p>
      )}

      {(rec || meta) && (
        <>
          <header>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="font-mono text-lg text-[var(--color-ink)]">{scenario}</h1>
              <StatusPill status={rec?.status || "running"} />
            </div>
            {copy && (
              <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-[var(--color-ink-muted)]">
                {copy.impact}
              </p>
            )}
            <p className="mt-1 font-mono text-[0.7rem] text-[var(--color-ink-faint)]">
              {id}
              {rec && ` · ${fmtTime(rec.created_at)}`}
            </p>
          </header>

          {rec && (
            <StatRow>
              <Stat label="duration" value={fmtDuration(rec.elapsed_s)} />
              <Stat label="iterations" value={rec.iterations} term="tool-loop" />
              <Stat
                label="tokens"
                value={`${fmtTokens(rec.usage?.input_tokens)}/${fmtTokens(rec.usage?.output_tokens)}`}
                sub="in / out"
              />
              {rec.diagnosis && <Stat label="confidence" value={rec.diagnosis.confidence} />}
              {rec.redactions > 0 && (
                <Stat label="redactions" value={rec.redactions} term="redaction" sub="tool output" />
              )}
              <Stat label="disposition" value={rec.disposition || "—"} term="disposition" />
            </StatRow>
          )}

          <Panel title="alert" bodyClass="p-0">
            <pre className="overflow-x-auto whitespace-pre-wrap break-words p-3.5 font-mono text-[0.8rem] leading-relaxed text-[var(--color-ink-muted)]">
              {rec?.alert || meta?.alert}
            </pre>
          </Panel>

          {phase === "running" && <ConsoleStream events={events} streaming={streaming} />}
          {rec && <Proposal record={rec} />}
          {rec?.status === "awaiting-approval" && <ApprovalForm record={rec} onResolved={setRec} />}
        </>
      )}
    </div>
  );
}

function seed(events) {
  const seen = new Set();
  const out = [];
  const now = Date.now();
  for (const e of events) {
    const k = eventKey(e);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push({ ...e, t: now }); // replayed history — all ~same time, fine
  }
  return out;
}

function ConsoleStream({ events, streaming }) {
  const rows = buildTimeline(events);
  const tone = {
    tool: "var(--color-accent)",
    warn: "var(--color-warn)",
    error: "var(--color-critical)",
    strong: "var(--color-ink)",
    muted: "var(--color-ink-faint)",
  };
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-mono text-[0.68rem] font-medium uppercase tracking-[0.13em] text-[var(--color-ink-faint)]">
          progress
        </span>
        <Term term="sse" />
        <span className="font-mono text-[0.68rem] text-[var(--color-ink-faint)]">
          {streaming ? "live — ~30–60s" : ""}
        </span>
      </div>
      <Panel
        title="run.log"
        right={
          streaming ? (
            <span className="flex items-center gap-1.5 text-[var(--color-accent)]">
              <span className="led dot-pending" /> streaming
            </span>
          ) : (
            <span className="text-[var(--color-ink-faint)]">closed</span>
          )
        }
        bodyClass="p-0"
      >
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-[0.78rem]">
            <tbody>
              {rows.map((r, i) => {
                const last = i === rows.length - 1;
                return (
                  <tr key={r.id} className="border-t first:border-t-0" style={{ borderColor: "var(--color-border)" }}>
                    <td className="whitespace-nowrap py-1.5 pl-3.5 pr-3 align-top text-[var(--color-ink-faint)]">
                      {fmtElapsed(r.elapsed)}
                    </td>
                    <td
                      className="whitespace-nowrap py-1.5 pr-3 align-top"
                      style={{ color: tone[r.tone] || "var(--color-ink-muted)" }}
                    >
                      {r.phase}
                    </td>
                    <td className="w-full py-1.5 pr-3 align-top text-[var(--color-ink-muted)]">
                      <span className="break-all">{r.detail}</span>
                      {last && streaming && r.pending && <span className="cursor-blink" />}
                    </td>
                    <td className="py-1.5 pr-3.5 align-top text-right">
                      {r.ok && <Check size={13} className="inline text-[var(--color-ok)]" />}
                      {r.err && <X size={13} className="inline text-[var(--color-critical)]" />}
                      {r.pending && !last && (
                        <span className="led dot-pending" style={{ color: "var(--color-accent)" }} />
                      )}
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td className="p-3.5 text-[var(--color-ink-faint)] cursor-blink">waiting for the loop</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
