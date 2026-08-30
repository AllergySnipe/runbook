import { useMemo, useState } from "react";

// A small multi-line time chart for a query_metrics result. Hand-rolled SVG.
// Colour: a single-hue sequential ramp on the accent — the series are one metric
// at ordered quantiles (p50 < p95 < p99), so higher quantile = more opaque +
// thicker. CVD-safe by construction (one hue). Single-series charts use the
// accent flat. Follows the dataviz method: thin marks, recessive axes, a hover
// crosshair, the last point directly labelled, one y-axis only.

const W = 640;
const H = 150;
const PAD = { t: 12, r: 46, b: 20, l: 40 };

const RAMP = [0.45, 0.62, 0.8, 1]; // opacity by series index

export default function MetricChart({ series }) {
  const [hoverX, setHoverX] = useState(null);

  const model = useMemo(() => {
    const parsed = series.map((s) => ({
      key: labelOf(s.labels) || s.unit || "value",
      unit: s.unit,
      summary: s.summary,
      pts: (s.points || []).map(([iso, v]) => ({ t: Date.parse(iso), v })),
    }));
    const all = parsed.flatMap((s) => s.pts);
    if (all.length === 0) return null;
    const tMin = Math.min(...all.map((p) => p.t));
    const tMax = Math.max(...all.map((p) => p.t));
    const vMax = Math.max(...all.map((p) => p.v));
    const x = (t) => PAD.l + ((t - tMin) / (tMax - tMin || 1)) * (W - PAD.l - PAD.r);
    const y = (v) => PAD.t + (1 - v / (vMax * 1.08 || 1)) * (H - PAD.t - PAD.b);
    return { parsed, tMin, tMax, vMax, x, y };
  }, [series]);

  if (!model) return <p className="font-mono text-xs text-[var(--color-ink-faint)]">no points</p>;
  const { parsed, tMin, tMax, x, y } = model;

  const idxAt = (px) => {
    const ref = parsed[0].pts;
    let best = 0;
    let bd = Infinity;
    ref.forEach((p, i) => {
      const d = Math.abs(x(p.t) - px);
      if (d < bd) {
        bd = d;
        best = i;
      }
    });
    return best;
  };
  const hi = hoverX == null ? null : idxAt(hoverX);
  const hiT = hi == null ? null : parsed[0].pts[hi]?.t;

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        style={{ maxHeight: 180 }}
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          setHoverX(((e.clientX - r.left) / r.width) * W);
        }}
        onMouseLeave={() => setHoverX(null)}
      >
        {/* baseline */}
        <line
          x1={PAD.l}
          x2={W - PAD.r}
          y1={H - PAD.b}
          y2={H - PAD.b}
          stroke="var(--color-border-strong)"
          strokeWidth="1"
        />
        {/* y ticks: max + mid */}
        {[model.vMax, model.vMax / 2].map((v, i) => (
          <g key={i}>
            <text
              x={PAD.l - 6}
              y={y(v) + 3}
              textAnchor="end"
              className="fill-[var(--color-ink-faint)]"
              style={{ fontSize: 9, fontFamily: "var(--font-mono)" }}
            >
              {fmtNum(v)}
            </text>
          </g>
        ))}
        {/* x ends */}
        {[tMin, tMax].map((t, i) => (
          <text
            key={i}
            x={x(t)}
            y={H - 6}
            textAnchor={i === 0 ? "start" : "end"}
            className="fill-[var(--color-ink-faint)]"
            style={{ fontSize: 9, fontFamily: "var(--font-mono)" }}
          >
            {fmtClock(t)}
          </text>
        ))}

        {/* series */}
        {parsed.map((s, si) => {
          const op = parsed.length === 1 ? 1 : RAMP[Math.min(si, RAMP.length - 1)];
          const d = s.pts.map((p, i) => `${i ? "L" : "M"}${x(p.t)},${y(p.v)}`).join(" ");
          const last = s.pts[s.pts.length - 1];
          return (
            <g key={s.key}>
              <path
                d={d}
                fill="none"
                stroke="var(--color-accent)"
                strokeOpacity={op}
                strokeWidth={si === parsed.length - 1 && parsed.length > 1 ? 2.25 : 1.75}
                strokeLinejoin="round"
              />
              {last && (
                <text
                  x={x(last.t) + 5}
                  y={y(last.v) + 3}
                  className="fill-[var(--color-ink-muted)]"
                  style={{ fontSize: 9, fontFamily: "var(--font-mono)" }}
                >
                  {s.key}
                </text>
              )}
            </g>
          );
        })}

        {/* hover crosshair */}
        {hi != null && hiT != null && (
          <>
            <line
              x1={x(hiT)}
              x2={x(hiT)}
              y1={PAD.t}
              y2={H - PAD.b}
              stroke="var(--color-border-strong)"
              strokeWidth="1"
            />
            {parsed.map((s, si) => {
              const p = s.pts[hi];
              if (!p) return null;
              return (
                <circle
                  key={si}
                  cx={x(p.t)}
                  cy={y(p.v)}
                  r="3.2"
                  fill="var(--color-bg)"
                  stroke="var(--color-accent)"
                  strokeWidth="1.5"
                />
              );
            })}
          </>
        )}
      </svg>

      {hi != null && hiT != null && (
        <div className="pointer-events-none absolute left-2 top-1 rounded border bg-[var(--color-surface-2)] px-2 py-1 font-mono text-[0.68rem] text-[var(--color-ink-muted)] shadow">
          <div className="text-[var(--color-ink-faint)]">{fmtClock(hiT)}</div>
          {parsed.map((s) => (
            <div key={s.key}>
              {s.key} <span className="text-[var(--color-ink)]">{fmtNum(s.pts[hi]?.v)}</span>
              {s.unit && s.unit !== "ratio" ? ` ${s.unit}` : ""}
            </div>
          ))}
        </div>
      )}

      {/* summary strip */}
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 font-mono text-[0.68rem] text-[var(--color-ink-faint)]">
        {parsed.map((s) => (
          <span key={s.key}>
            {s.key}: p50 {fmtNum(s.summary?.p50)} · p99 {fmtNum(s.summary?.p99)} ·{" "}
            <span
              style={{
                color:
                  s.summary?.trend === "rising"
                    ? "var(--color-serious)"
                    : s.summary?.trend === "falling"
                      ? "var(--color-ok)"
                      : "var(--color-ink-faint)",
              }}
            >
              {s.summary?.trend}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

function labelOf(labels) {
  if (!labels || Object.keys(labels).length === 0) return null;
  return Object.values(labels).join(" ");
}
function fmtNum(v) {
  if (v == null) return "—";
  if (v === 0) return "0";
  if (Math.abs(v) >= 100) return v.toFixed(0);
  if (Math.abs(v) >= 1) return v.toFixed(2);
  return v.toPrecision(2);
}
function fmtClock(t) {
  return new Date(t).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}
