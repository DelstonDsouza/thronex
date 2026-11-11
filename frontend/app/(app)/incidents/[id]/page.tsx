"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Badge from "@/components/Badge";
import { apiGet, apiPost } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import type { IncidentDetail, Me } from "@/lib/types";

// Mirrors the allowed transitions in backend/app/services/incident_workflow.py
const NEXT: Record<string, string[]> = {
  detected: ["acknowledged", "investigating", "resolved"],
  acknowledged: ["investigating", "mitigating", "resolved"],
  investigating: ["mitigating", "resolved"],
  mitigating: ["investigating", "resolved"],
  resolved: ["investigating", "closed"],
  closed: [],
};

export default function IncidentPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [incident, setIncident] = useState<IncidentDetail | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [inc, user] = await Promise.all([
        apiGet<IncidentDetail>(`/incidents/${id}`),
        apiGet<Me>("/auth/me"),
      ]);
      setIncident(inc);
      setMe(user);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [id]);

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);

  async function act(fn: () => Promise<IncidentDetail>) {
    try {
      setIncident(await fn());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }

  function changeStatus(next: string) {
    let notes: string | undefined;
    if (next === "resolved") {
      const answer = window.prompt("Resolution notes (required):");
      if (!answer || !answer.trim()) return;
      notes = answer.trim();
    }
    act(() => apiPost<IncidentDetail>(`/incidents/${id}/status`, { status: next, resolution_notes: notes }));
  }

  if (error && !incident) return <p role="alert" className="text-red-300">{error}</p>;
  if (!incident) return <p className="text-zinc-400">Loading...</p>;

  const options = NEXT[incident.status] ?? [];
  const label = (s: string) =>
    incident.status === "resolved" && s === "investigating"
      ? "Reopen"
      : s === "resolved"
        ? "Resolve"
        : s.charAt(0).toUpperCase() + s.slice(1);

  return (
    <div className="space-y-5">
      <Link href="/incidents" className="text-sm text-sky-400 hover:underline">← All incidents</Link>
      <div>
        <h1 className="text-xl font-semibold">#{incident.id} {incident.title}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Badge value={incident.severity} />
          <Badge value={incident.status} />
          <span className="text-sm text-zinc-400">{incident.category.replace(/_/g, " ")}</span>
          <span className="text-sm text-zinc-500">· started {fmtTime(incident.started_at)}</span>
        </div>
        <p className="mt-2 text-sm text-zinc-400">{incident.description}</p>
      </div>

      {error && <p role="alert" className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">{error}</p>}

      <div className="flex flex-wrap gap-2">
        {options.map((s) => (
          <button key={s} onClick={() => changeStatus(s)} className="rounded border border-zinc-700 px-3 py-1 text-sm hover:bg-zinc-800">
            {label(s)}
          </button>
        ))}
        {me && incident.assigned_user_id !== me.id && incident.status !== "closed" && (
          <button onClick={() => act(() => apiPost<IncidentDetail>(`/incidents/${id}/assign`, { user_id: me.id }))} className="rounded border border-zinc-700 px-3 py-1 text-sm hover:bg-zinc-800">
            Assign to me
          </button>
        )}
        {incident.assigned_user_id !== null && <span className="self-center text-xs text-zinc-500">Assigned to user #{incident.assigned_user_id}</span>}
      </div>

      {incident.root_cause_hypothesis && (
        <section className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
          <h2 className="mb-1 font-medium">Root cause hypothesis</h2>
          <p className="text-sm text-zinc-300">{incident.root_cause_hypothesis}</p>
        </section>
      )}

      {incident.recommended_actions.length > 0 && (
        <section className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <h2 className="mb-2 font-medium">Recommended investigation steps</h2>
          <ul className="list-disc space-y-1 pl-5 text-sm text-zinc-300">
            {incident.recommended_actions.map((a) => <li key={a}>{a}</li>)}
          </ul>
        </section>
      )}

      {incident.resolution_notes && (
        <section className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4">
          <h2 className="mb-1 font-medium">Resolution notes</h2>
          <p className="text-sm">{incident.resolution_notes}</p>
        </section>
      )}

      <section className="rounded-lg border border-zinc-800 bg-zinc-900">
        <h2 className="border-b border-zinc-800 p-3 font-medium">Anomalies ({incident.anomalies.length})</h2>
        <ul>
          {incident.anomalies.map((a) => (
            <li key={a.id} className="border-t border-zinc-800 p-3 text-sm first:border-t-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge value={a.severity} />
                <span className="font-medium">{a.metric_name}</span>
                <span className="text-zinc-400">observed {a.observed_value.toPrecision(3)} vs baseline {a.baseline_value.toPrecision(3)}</span>
                <span className="text-xs text-zinc-500">{a.ongoing ? "ongoing" : "ended"}</span>
              </div>
              <p className="mt-1 text-xs text-zinc-500">{a.explanation}</p>
            </li>
          ))}
        </ul>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-lg border border-zinc-800 bg-zinc-900">
          <h2 className="border-b border-zinc-800 p-3 font-medium">Timeline</h2>
          <ul className="max-h-96 overflow-y-auto">
            {[...incident.events].reverse().map((e) => (
              <li key={e.id} className="border-t border-zinc-800 p-3 text-sm first:border-t-0">
                <div className="text-xs text-zinc-500">{fmtTime(e.created_at)} · {e.event_type.replace(/_/g, " ")}</div>
                <div>{e.message}</div>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-lg border border-zinc-800 bg-zinc-900">
          <h2 className="border-b border-zinc-800 p-3 font-medium">Comments ({incident.comments.length})</h2>
          <ul>
            {incident.comments.map((c) => (
              <li key={c.id} className="border-t border-zinc-800 p-3 text-sm first:border-t-0">
                <div className="text-xs text-zinc-500">{fmtTime(c.created_at)} · user #{c.user_id}</div>
                <div>{c.body}</div>
              </li>
            ))}
          </ul>
          <form
            className="flex gap-2 border-t border-zinc-800 p-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!comment.trim()) return;
              act(() => apiPost<IncidentDetail>(`/incidents/${id}/comments`, { body: comment.trim() }));
              setComment("");
            }}
          >
            <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Add a comment..." className="flex-1 rounded border border-zinc-700 bg-zinc-950 px-3 py-1 text-sm" />
            <button className="rounded bg-sky-600 px-3 py-1 text-sm hover:bg-sky-500">Post</button>
          </form>
        </section>
      </div>
    </div>
  );
}