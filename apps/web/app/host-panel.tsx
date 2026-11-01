"use client";

import { useEffect, useState } from "react";
import { api } from "./api-client";

type Host = {
  project_id: string; host_id: string | null;
  status: "unassigned" | "connected" | "waiting" | "stale" | "unavailable";
  observed_at: string; last_seen_at: string | null; freshness_seconds: number | null; stale_seconds: number;
  cpu_usage_percent: number | null; memory_usage_percent: number | null;
  memory_used_bytes: number | null; memory_total_bytes: number | null; detail: string;
};
type Update = { project: string; data?: Host; receivedAt?: number; error?: string };

function percent(value: number | null | undefined) { return value == null ? "—" : `${value.toFixed(1)}%`; }
function gib(value: number) { return `${(value / 1024 ** 3).toFixed(1)} GiB`; }

export function HostPanel({ projectId }: { projectId: string }) {
  const [update, setUpdate] = useState<Update>({ project: "" });
  const [revision, setRevision] = useState(0);
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 5000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!projectId) return;
    const abort = new AbortController();
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      try {
        const data = await api<Host>(`/projects/${encodeURIComponent(projectId)}/host`, {
          signal: AbortSignal.any([abort.signal, AbortSignal.timeout(10000)]),
        });
        if (!stopped && data.project_id === projectId) setUpdate({ project: projectId, data, receivedAt: Date.now() });
      } catch {
        if (!stopped) setUpdate({ project: projectId, error: "Host updates are unavailable. Resource usage is unknown; retry refresh." });
      } finally {
        if (!stopped) timer = setTimeout(load, 15000);
      }
    }
    void load();
    return () => { stopped = true; abort.abort(); clearTimeout(timer); };
  }, [projectId, revision]);

  const current = update.project === projectId ? update : undefined;
  const data = current?.data;
  const elapsed = current?.receivedAt ? Math.max(0, (clock - current.receivedAt) / 1000) : 0;
  const delayed = elapsed > 30;
  const stale = data?.freshness_seconds != null && data.freshness_seconds + elapsed > data.stale_seconds;
  const measured = data?.status === "connected" && !delayed && !stale;
  const status = delayed ? "Updates delayed" : stale ? "Stale" : data ? {
    connected: "Receiving metrics", unassigned: "No host assigned", waiting: "Waiting for telemetry",
    stale: "Stale", unavailable: "Collection unavailable",
  }[data.status] : current?.error ? "Unavailable" : "Reading host…";

  return <section className="host-panel" aria-labelledby="host-heading">
    <div className="section-heading"><div><h2 id="host-heading">Host resources</h2>
      <p className="muted">The monitoring machine assigned to the selected project.</p></div>
      {projectId && <button className="quiet" onClick={() => setRevision((value) => value + 1)}>Refresh host</button>}</div>
    {!projectId ? <p className="empty">Create a project to assign a monitoring host.</p> : <>
      <p className="host-state" role="status">{status}</p>
      {current?.error && <p role="alert" className="error">{current.error}</p>}
      {data?.status !== "unassigned" && <dl className="host-signals">
        <div><dt>CPU usage</dt><dd>{percent(measured ? data?.cpu_usage_percent : null)}</dd><small>Two-minute average</small></div>
        <div><dt>Memory usage</dt><dd>{percent(measured ? data?.memory_usage_percent : null)}</dd>
          <small>{measured && data?.memory_used_bytes != null && data.memory_total_bytes != null
            ? `${gib(data.memory_used_bytes)} of ${gib(data.memory_total_bytes)}` : "Used / total unknown"}</small></div>
      </dl>}
      {data && <p className="muted">{delayed || stale ? "Fresh host updates are unavailable; resource usage is unknown." : data.detail}</p>}
      {data?.status === "unassigned" && <p className="muted">Project ID for operator setup: <code>{projectId}</code></p>}
      {data?.host_id && <p className="muted">Last seen: {data.last_seen_at ? new Date(data.last_seen_at).toLocaleString() : "No recent samples"} · Stale after {data.stale_seconds} seconds</p>}
    </>}
  </section>;
}
