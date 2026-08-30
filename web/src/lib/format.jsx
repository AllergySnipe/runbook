export const STATUS_STYLE = {
  running: "bg-blue-500/15 text-blue-300 ring-blue-500/30",
  "awaiting-approval": "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  resolved: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  rejected: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  escalated: "bg-orange-500/15 text-orange-300 ring-orange-500/30",
  "short-circuited": "bg-zinc-500/15 text-zinc-400 ring-zinc-500/30",
};

export function StatusPill({ status }) {
  const cls = STATUS_STYLE[status] || "bg-zinc-500/15 text-zinc-400 ring-zinc-500/30";
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ring-1 ${cls}`}>{status}</span>
  );
}

export const fmtTime = (iso) => {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
};
