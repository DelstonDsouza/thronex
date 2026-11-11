export const fmtRate = (v: number | null): string =>
  v === null ? "–" : `${v.toFixed(v < 10 ? 2 : 1)}/s`;

export const fmtPercent = (v: number | null): string =>
  v === null ? "–" : `${(v * 100).toFixed(1)}%`;

export const fmtSeconds = (v: number | null): string => {
  if (v === null) return "–";
  return v < 1 ? `${Math.round(v * 1000)} ms` : `${v.toFixed(2)} s`;
};

export const fmtMemory = (v: number | null): string =>
  v === null ? "–" : `${(v / 1048576).toFixed(0)} MB`;

export const fmtCores = (v: number | null): string =>
  v === null ? "–" : `${v.toFixed(3)} cores`;

export const fmtTime = (iso: string | null): string =>
  iso ? new Date(iso).toLocaleString() : "–";

export const fmtDuration = (seconds: number | null): string => {
  if (seconds === null) return "–";
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 5400) return `${(seconds / 60).toFixed(1)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
};