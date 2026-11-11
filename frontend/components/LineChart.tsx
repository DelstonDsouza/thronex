import type { Point } from "@/lib/types";

interface Props {
  title: string;
  points: Point[];
  format: (v: number | null) => string;
  color?: string;
}

const W = 320;
const H = 110;
const PAD = 6;

export default function LineChart({ title, points, format, color = "#38bdf8" }: Props) {
  const valid = points.filter((p): p is [number, number] => p[1] !== null);
  const last = valid.length ? valid[valid.length - 1][1] : null;

  let path = "";
  let top = 0;
  if (valid.length >= 2) {
    const xs = valid.map((p) => p[0]);
    const ys = valid.map((p) => p[1]);
    const x0 = Math.min(...xs);
    const x1 = Math.max(...xs);
    const lo = Math.min(0, ...ys);
    top = Math.max(...ys);
    const hi = top === lo ? lo + 1 : top;
    let pen = false;
    for (const [t, v] of points) {
      if (v === null) {
        pen = false; // gap in the data
        continue;
      }
      const x = PAD + ((t - x0) / (x1 - x0 || 1)) * (W - 2 * PAD);
      const y = H - PAD - ((v - lo) / (hi - lo)) * (H - 2 * PAD);
      path += `${pen ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)} `;
      pen = true;
    }
  }

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-sm text-zinc-400">{title}</span>
        <span className="text-sm font-semibold">{format(last)}</span>
      </div>
      {path ? (
        <svg viewBox={`0 0 ${W} ${H}`} className="h-28 w-full" role="img" aria-label={title}>
          <line x1={PAD} x2={W - PAD} y1={H - PAD} y2={H - PAD} stroke="#3f3f46" />
          <path d={path} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
        </svg>
      ) : (
        <div className="flex h-28 items-center justify-center text-sm text-zinc-500">
          No data in this window
        </div>
      )}
      <div className="text-right text-xs text-zinc-500">peak {format(path ? top : null)}</div>
    </div>
  );
}