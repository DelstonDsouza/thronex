const COLORS: Record<string, string> = {
  healthy: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  degraded: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  unhealthy: "bg-red-500/15 text-red-300 border-red-500/30",
  unknown: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30",
  critical: "bg-red-500/15 text-red-300 border-red-500/30",
  high: "bg-orange-500/15 text-orange-300 border-orange-500/30",
  medium: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  low: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  informational: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30",
  detected: "bg-red-500/15 text-red-300 border-red-500/30",
  acknowledged: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  investigating: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  mitigating: "bg-violet-500/15 text-violet-300 border-violet-500/30",
  resolved: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  closed: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30",
  recommended: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  executing: "bg-violet-500/15 text-violet-300 border-violet-500/30",
  succeeded: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  failed: "bg-red-500/15 text-red-300 border-red-500/30",
  rejected: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30",
};

export default function Badge({ value }: { value: string }) {
  const style = COLORS[value] ?? COLORS.unknown;
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${style}`}>
      {value.replace(/_/g, " ")}
    </span>
  );
}