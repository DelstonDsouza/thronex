"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import Badge from "@/components/Badge";
import LineChart from "@/components/LineChart";
import { apiGet, apiPost } from "@/lib/api";
import {
  fmtCores,
  fmtDuration,
  fmtMemory,
  fmtPercent,
  fmtRate,
  fmtSeconds,
  fmtTime,
} from "@/lib/format";
import type {
  Application,
  DetectionReport,
  Environment,
  EnvironmentSummary,
  IncidentStats,
  IncidentSummary,
  Me,
  ServiceMetrics,
} from "@/lib/types";

interface EnvBlock {
  app: Application;
  env: Environment;
  summary: EnvironmentSummary | null;
  error?: string;
}

function Kpi({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
    </div>
  );
}

export default function Overview() {
  const [blocks, setBlocks] = useState<EnvBlock[]>([]);
  const [appCount, setAppCount] = useState(0);
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [stats, setStats] = useState<IncidentStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<number | null>(null);
  const [metrics, setMetrics] = useState<ServiceMetrics | null>(null);
  const [metricsError, setMetricsError] = useState<string | null>(null);
  const [detectMsg, setDetectMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const me = await apiGet<Me>("/auth/me");
      const org = me.memberships[0]?.organization_id;
      if (!org) {
        setError("Your account has no organization.");
        return;
      }
      const apps = await apiGet<Application[]>(`/organizations/${org}/applications`);
      setAppCount(apps.length);
      const list: EnvBlock[] = [];
      for (const app of apps) {
        const envs = await apiGet<Environment[]>(`/applications/${app.id}/environments`);
        for (const env of envs) {
          try {
            const summary = await apiGet<EnvironmentSummary>(
              `/environments/${env.id}/monitoring/summary`,
            );
            list.push({ app, env, summary });
          } catch (e) {
            list.push({ app, env, summary: null, error: e instanceof Error ? e.message : "failed" });
          }
        }
      }
      setBlocks(list);
      const [inc, st] = await Promise.all([
        apiGet<IncidentSummary[]>(`/organizations/${org}/incidents?limit=8`),
        apiGet<IncidentStats>(`/organizations/${org}/incidents/stats`),
      ]);
      setIncidents(inc);
      setStats(st);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);

  const allServices = blocks.flatMap((b) =>
    (b.summary?.services ?? []).map((s) => ({ ...s, env: b.env, app: b.app })),
  );

  useEffect(() => {
    if (selected === null && allServices.length) setSelected(allServices[0].service_id);
  }, [allServices, selected]);

  useEffect(() => {
    if (selected === null) return;
    let cancelled = false;
    const fetchMetrics = async () => {
      try {
        const m = await apiGet<ServiceMetrics>(`/services/${selected}/metrics?minutes=15`);
        if (!cancelled) {
          setMetrics(m);
          setMetricsError(null);
        }
      } catch (e) {
        if (!cancelled) setMetricsError(e instanceof Error ? e.message : "failed");
      }
    };
    fetchMetrics();
    const t = setInterval(fetchMetrics, 10000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [selected]);

  async function runDetection(envId: number) {
    setDetectMsg("Running detection...");
    try {
      const r = await apiPost<DetectionReport>(`/environments/${envId}/detection/run`);
      setDetectMsg(
        r.results.map((x) => `${x.service}: ${x.outcome}`).join(" · ") +
          ` — ${r.incident_ids.length} incident(s) touched`,
      );
      load();
    } catch (e) {
      setDetectMsg(e instanceof Error ? e.message : "Detection failed");
    }
  }

  const healthy = allServices.filter((s) => s.computed_status === "healthy").length;
  const bad = allServices.filter(
    (s) => s.computed_status === "degraded" || s.computed_status === "unhealthy",
  ).length;
  const series = metrics?.series ?? {};

  if (loading) return <p className="text-zinc-400">Loading...</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Overview</h1>
        <span className="text-xs text-zinc-500">Refreshes every 10 seconds</span>
      </div>

      {error && <p role="alert" className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">{error}</p>}

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Kpi label="Applications" value={appCount} />
        <Kpi label="Services" value={allServices.length} />
        <Kpi label="Healthy" value={healthy} />
        <Kpi label="Degraded / unhealthy" value={bad} />
        <Kpi label="Open incidents" value={stats?.open ?? 0} />
        <Kpi label="Total incidents" value={stats?.total ?? 0} />
      </section>
      <p className="text-xs text-zinc-500">
        MTTD: {fmtDuration(stats?.mttd_seconds ?? null)} · MTTR: {fmtDuration(stats?.mttr_seconds ?? null)}
      </p>

      {blocks.length === 0 && !error && (
        <p className="rounded border border-zinc-800 p-4 text-sm text-zinc-400">
          No applications yet. Create one in the API docs (http://localhost:8000/docs), then it will appear here.
        </p>
      )}

      {blocks.map((b) => (
        <section key={b.env.id} className="rounded-lg border border-zinc-800 bg-zinc-900">
          <div className="flex items-center justify-between border-b border-zinc-800 p-3">
            <div>
              <span className="font-medium">{b.app.name}</span>
              <span className="text-zinc-500"> / {b.env.name} ({b.env.env_type})</span>
            </div>
            <button onClick={() => runDetection(b.env.id)} className="rounded border border-zinc-700 px-3 py-1 text-xs hover:bg-zinc-800">
              Run detection now
            </button>
          </div>
          {b.error && <p className="p-3 text-sm text-amber-300">Monitoring unavailable: {b.error}</p>}
          {b.summary && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-zinc-500">
                  <tr>
                    <th className="p-3">Service</th>
                    <th className="p-3">Status</th>
                    <th className="p-3">Requests</th>
                    <th className="p-3">Error rate</th>
                    <th className="p-3">P95 latency</th>
                  </tr>
                </thead>
                <tbody>
                  {b.summary.services.map((s) => (
                    <tr key={s.service_id} className="cursor-pointer border-t border-zinc-800 hover:bg-zinc-800/40" onClick={() => setSelected(s.service_id)}>
                      <td className="p-3 font-medium">{s.name}</td>
                      <td className="p-3"><Badge value={s.computed_status} /></td>
                      <td className="p-3">{fmtRate(s.request_rate)}</td>
                      <td className="p-3">{fmtPercent(s.error_rate)}</td>
                      <td className="p-3">{fmtSeconds(s.p95_latency_seconds)}</td>
                    </tr>
                  ))}
                  {b.summary.services.length === 0 && (
                    <tr><td colSpan={5} className="p-3 text-zinc-500">No services registered.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ))}
      {detectMsg && <p className="text-xs text-zinc-400">{detectMsg}</p>}

      {allServices.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center gap-3">
            <h2 className="font-medium">Live metrics (last 15 minutes)</h2>
            <select value={selected ?? ""} onChange={(e) => setSelected(Number(e.target.value))} className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm">
              {allServices.map((s) => (
                <option key={s.service_id} value={s.service_id}>{s.name} ({s.env.name})</option>
              ))}
            </select>
          </div>
          {metricsError && <p className="text-sm text-amber-300">{metricsError}</p>}
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <LineChart title="Request rate" points={series.request_rate ?? []} format={fmtRate} />
            <LineChart title="P95 latency" points={series.latency_p95 ?? []} format={fmtSeconds} color="#f59e0b" />
            <LineChart title="Error rate" points={series.error_rate ?? []} format={fmtPercent} color="#f87171" />
            <LineChart title="CPU" points={series.cpu_cores ?? []} format={fmtCores} color="#a78bfa" />
            <LineChart title="Memory" points={series.memory_bytes ?? []} format={fmtMemory} color="#34d399" />
            <LineChart title="P99 latency" points={series.latency_p99 ?? []} format={fmtSeconds} color="#fb923c" />
          </div>
        </section>
      )}

      <section className="rounded-lg border border-zinc-800 bg-zinc-900">
        <div className="flex items-center justify-between border-b border-zinc-800 p-3">
          <h2 className="font-medium">Recent incidents</h2>
          <Link href="/incidents" className="text-sm text-sky-400 hover:underline">View all</Link>
        </div>
        {incidents.length === 0 ? (
          <p className="p-3 text-sm text-zinc-500">No incidents recorded.</p>
        ) : (
          <ul>
            {incidents.map((i) => (
              <li key={i.id} className="border-t border-zinc-800 first:border-t-0">
                <Link href={`/incidents/${i.id}`} className="flex flex-wrap items-center gap-3 p-3 hover:bg-zinc-800/40">
                  <Badge value={i.severity} />
                  <Badge value={i.status} />
                  <span className="flex-1 text-sm">{i.title}</span>
                  <span className="text-xs text-zinc-500">{fmtTime(i.created_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}