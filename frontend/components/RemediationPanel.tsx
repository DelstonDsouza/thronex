"use client";

import { useCallback, useEffect, useState } from "react";
import Badge from "@/components/Badge";
import { apiGet, apiPost } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import type { Remediation } from "@/lib/types";

interface Props {
  incidentId: number;
  incidentStatus: string;
  onChanged: () => void;
}

export default function RemediationPanel({ incidentId, incidentStatus, onChanged }: Props) {
  const [items, setItems] = useState<Remediation[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await apiGet<Remediation[]>(`/incidents/${incidentId}/remediations`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [incidentId]);

  useEffect(() => {
    load();
  }, [load]);

  async function run(label: string, path: string) {
    setBusy(label);
    setError(null);
    try {
      await apiPost(path);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(null);
      await load();
      onChanged();
    }
  }

  const isOpen = ["detected", "acknowledged", "investigating", "mitigating"].includes(incidentStatus);

  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900">
      <div className="flex items-center justify-between border-b border-zinc-800 p-3">
        <h2 className="font-medium">Remediation</h2>
        {isOpen && (
          <button
            disabled={busy !== null}
            onClick={() => run("suggest", `/incidents/${incidentId}/remediations`)}
            className="rounded border border-zinc-700 px-3 py-1 text-sm hover:bg-zinc-800 disabled:opacity-50"
          >
            Suggest restart
          </button>
        )}
      </div>
      {error && <p role="alert" className="p-3 text-sm text-red-300">{error}</p>}
      {items.length === 0 && <p className="p-3 text-sm text-zinc-500">No remediation actions yet.</p>}
      <ul>
        {items.map((rem) => (
          <li key={rem.id} className="space-y-2 border-t border-zinc-800 p-3 text-sm first:border-t-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge value={rem.status} />
              <span className="font-medium">Restart {rem.service_name}</span>
              <span className="text-xs text-zinc-500">container {rem.container} · {fmtTime(rem.created_at)}</span>
            </div>
            <p className="text-zinc-400">{rem.reason}</p>
            <p className="text-zinc-400"><span className="text-zinc-300">Expected impact:</span> {rem.expected_impact}</p>
            {rem.result_message && <p className="text-zinc-300">Result: {rem.result_message}</p>}
            {rem.verification && (
              <p className={rem.verified ? "text-emerald-300" : "text-amber-300"}>{rem.verification}</p>
            )}
            <div className="flex gap-2">
              {rem.status === "recommended" && (
                <>
                  <button
                    disabled={busy !== null}
                    onClick={() => {
                      if (window.confirm(`Restart ${rem.service_name} now? Requests will fail briefly.`))
                        run("approve", `/remediations/${rem.id}/approve`);
                    }}
                    className="rounded bg-emerald-700 px-3 py-1 hover:bg-emerald-600 disabled:opacity-50"
                  >
                    {busy === "approve" ? "Restarting (up to 60 s)..." : "Approve & run"}
                  </button>
                  <button
                    disabled={busy !== null}
                    onClick={() => run("reject", `/remediations/${rem.id}/reject`)}
                    className="rounded border border-zinc-700 px-3 py-1 hover:bg-zinc-800 disabled:opacity-50"
                  >
                    Reject
                  </button>
                </>
              )}
              {rem.status === "succeeded" && (
                <button
                  disabled={busy !== null}
                  onClick={() => run("verify", `/remediations/${rem.id}/verify`)}
                  className="rounded border border-zinc-700 px-3 py-1 hover:bg-zinc-800 disabled:opacity-50"
                >
                  {busy === "verify" ? "Checking..." : "Verify recovery"}
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}