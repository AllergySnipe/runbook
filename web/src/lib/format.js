export const fmtTime = (iso) => {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
};

export const fmtDuration = (s) => {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
};

export const fmtTokens = (n) => {
  if (n == null) return "—";
  if (n < 1000) return String(n);
  return `${(n / 1000).toFixed(1)}k`;
};

// Sub-cent estimates — show enough digits to be meaningful ($0.0043), not $0.00.
export const fmtUSD = (n) => {
  if (n == null) return "—";
  if (n === 0) return "$0";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  if (n < 1) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
};

export const SEVERITY_TONE = { SEV1: "critical", SEV2: "serious", SEV3: "warn" };
