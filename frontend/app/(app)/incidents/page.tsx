"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Badge from "@/components/Badge";
import { apiGet } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import type { IncidentSummary, Me } from "@/lib/types";

const STATUSES = ["", "detected", "acknowledged", "investigating", "mitigating", "resolved", "closed"];

export default function IncidentsPage() {
  const [items, setItems] = useState<IncidentSummary[]>([]);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await apiGet<Me>("/auth/me");
        const org = me.memberships[0]?.organization_id;
        const params = new URLSearchParams({ limit: "100" });
        if (status) params.set("status", status);
        if (search.trim()) params.set("q", search.trim());
        const data = await apiGet<IncidentSummary[]>(`/organizations/${org}/incidents?${params}`);
        if (!cancelled) {
          setItems(data);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status, search]);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Incidents</h1>
      <div className="flex flex-wrap gap-3">
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm">
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s === "" ? "All statuses" : s}</option>
          ))}
        </select>
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search title..." className="rounded border border-zinc-700 bg-zinc-900 px-3 py-1 text-sm" />
      </div>
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      {loading ? (
        <p className="text-zinc-400">Loading...</p>
      ) : items.length === 0 ? (
        <p className="rounded border border-zinc-800 p-4 text-sm text-zinc-500">No incidents match.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-zinc-800 bg-zinc-900">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-zinc-500">
              <tr>
                <th className="p-3">Severity</th>
                <th className="p-3">Status</th>
                <th className="p-3">Title</th>
                <th className="p-3">Category</th>
                <th className="p-3">Detected</th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id} className="border-t border-zinc-800 hover:bg-zinc-800/40">
                  <td className="p-3"><Badge value={i.severity} /></td>
                  <td className="p-3"><Badge value={i.status} /></td>
                  <td className="p-3"><Link href={`/incidents/${i.id}`} className="text-sky-400 hover:underline">#{i.id} {i.title}</Link></td>
                  <td className="p-3 text-zinc-400">{i.category.replace(/_/g, " ")}</td>
                  <td className="p-3 text-zinc-400">{fmtTime(i.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}