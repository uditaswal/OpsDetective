"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "./api-client";

type Project = { id: string; name: string };
type ServiceHealth = {
  id: string; name: string; environment: string;
  status: "healthy" | "degraded" | "disconnected";
  collection_status: "connected" | "stale" | "unavailable" | "waiting";
  request_rate_per_minute: number | null; error_rate_percent: number | null;
  latency_p95_ms: number | null; availability: boolean | null;
  last_seen_at: string | null; freshness_seconds: number | null; reasons: string[];
};
type Snapshot = {
  project_id: string; observed_at: string; services: ServiceHealth[];
  policy: { stale_seconds: number; error_rate_percent: number; latency_p95_ms: number; window_seconds: number };
};
type Update = {
  project: string; data?: Snapshot; receivedAt?: number; error?: string;
  mode: "connecting" | "live" | "polling";
};

function useHealth(projectId: string, revision: number) {
  const [update, setUpdate] = useState<Update>({ project: "", mode: "connecting" });
  useEffect(() => {
    if (!projectId) return;
    let stopped = false;
    let polling = false;
    let fetching = false;
    let source: EventSource | undefined;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    let watchdog: ReturnType<typeof setTimeout> | undefined;
    const abort = new AbortController();
    let mode: Update["mode"] = "connecting";
    const accept = (data: Snapshot) => {
      if (stopped || data.project_id !== projectId || !Array.isArray(data.services)) return;
      setUpdate((previous) => {
        if (previous.project === projectId && previous.data && Date.parse(previous.data.observed_at) > Date.parse(data.observed_at)) return { ...previous, mode };
        return { project: projectId, data, receivedAt: Date.now(), mode };
      });
    };
    const fetchSnapshot = async () => {
      if (stopped || fetching) return;
      fetching = true;
      try {
        const data = await api<Snapshot>(`/projects/${encodeURIComponent(projectId)}/health`, {
          signal: AbortSignal.any([abort.signal, AbortSignal.timeout(10000)]),
        });
        accept(data);
      } catch (error) {
        if (!stopped) {
          if (error instanceof ApiError && (error.status === 401 || error.status === 404)) {
            source?.close();
            stopped = true;
            setUpdate({ project: projectId, mode: "polling", error: "Access to this project ended. Sign in again or choose another project." });
            return;
          }
          setUpdate((previous) => ({ ...(previous.project === projectId ? previous : {}), project: projectId, mode,
            error: "Updates are unavailable. Last known values are shown; application health is unknown." }));
        }
      } finally {
        fetching = false;
        if (!stopped && polling) pollTimer = setTimeout(fetchSnapshot, 10000);
      }
    };
    const fallback = () => {
      if (stopped || polling) return;
      polling = true;
      mode = "polling";
      source?.close();
      clearTimeout(watchdog);
      setUpdate((previous) => ({ ...(previous.project === projectId ? previous : {}), project: projectId, mode }));
      void fetchSnapshot();
    };
    void fetchSnapshot();
    if (typeof EventSource === "undefined") fallback();
    else {
      source = new EventSource(`/api/v1/projects/${encodeURIComponent(projectId)}/health/stream`);
      watchdog = setTimeout(fallback, 15000);
      source.addEventListener("health", (event) => {
        try {
          const data: Snapshot = JSON.parse(event.data);
          if (data.project_id !== projectId || !Array.isArray(data.services)) { fallback(); return; }
          mode = "live";
          clearTimeout(watchdog);
          watchdog = setTimeout(fallback, 15000);
          accept(data);
        } catch { fallback(); }
      });
      source.addEventListener("access-lost", () => {
        stopped = true;
        source?.close();
        clearTimeout(watchdog);
        abort.abort();
        setUpdate({ project: projectId, mode: "polling", error: "Access to this project ended. Sign in again or choose another project." });
      });
      source.onerror = fallback;
    }
    return () => {
      stopped = true;
      abort.abort();
      source?.close();
      clearTimeout(pollTimer);
      clearTimeout(watchdog);
    };
  }, [projectId, revision]);
  return update.project === projectId ? update : { project: projectId, mode: "connecting" as const };
}

function number(value: number | null, suffix: string): string {
  return value === null ? "—" : `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}${suffix}`;
}

export function HealthPanel({ projects, revision }: { projects: Project[]; revision: number }) {
  const [selection, setSelection] = useState("");
  const [retry, setRetry] = useState(0);
  const [now, setNow] = useState(0);
  const projectId = projects.some((p) => p.id === selection) ? selection : projects[0]?.id ?? "";
  const update = useHealth(projectId, revision + retry);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(timer);
  }, []);
  const age = update.receivedAt ? Math.max(0, (now - update.receivedAt) / 1000) : 0;
  const staleUpdates = Boolean(update.data && age > 20);
  const unknown = Boolean(update.error || staleUpdates);
  const connection = update.error ? "Updates unavailable" : staleUpdates ? "Updates delayed" :
    update.mode === "live" ? "Live updates" : update.mode === "polling" ? "Polling every 10 seconds" : "Connecting live updates…";

  return <section className="health-section" aria-labelledby="health-heading">
    <div className="section-heading"><div><h2 id="health-heading">Service health</h2>
      <p className="muted">Application signals and collection health, shown separately.</p></div>
      {projectId && <div className="health-actions"><span className="muted" role="status">{connection}</span>
        <button className="quiet" onClick={() => setRetry((n) => n + 1)}>Refresh health</button></div>}
    </div>
    {projects.length === 0 ? <p className="empty">Add a project and register a service to start monitoring.</p> : <>
      <div className="health-filter"><label htmlFor="health-project">Project</label>
        <select id="health-project" value={projectId} onChange={(e) => setSelection(e.target.value)}>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        {update.data && <span className="muted">Updated <time dateTime={update.data.observed_at}>
          {new Date(update.data.observed_at).toLocaleTimeString()}</time></span>}
      </div>
      {(update.error || staleUpdates) && <p className="error" role="alert">{update.error ?? "Updates are delayed. Application health is unknown until a fresh update arrives."}</p>}
      {!update.data && !update.error && <p className="empty" role="status">Reading service signals…</p>}
      {update.data?.services.length === 0 && <p className="empty">No services in this project. Register one below to connect telemetry.</p>}
      <div className="health-list">{update.data?.services.map((service) => {
        const stale = service.freshness_seconds !== null && service.freshness_seconds + age > update.data!.policy.stale_seconds;
        const status = unknown || stale ? "disconnected" : service.status;
        const collection = unknown ? "Updates unavailable" : stale ? "Stale" :
          ({ connected: "Connected", stale: "Stale", unavailable: "Unavailable", waiting: "Waiting for telemetry" })[service.collection_status];
        return <article className="service-health" key={service.id} aria-label={`${service.name} health`}>
          <div className="service-heading"><div><h3>{service.name}</h3><p className="muted">{service.environment}</p></div>
            <span className={`health-status ${status}`}>{status === "healthy" ? "Healthy" : status === "degraded" ? "Degraded" : "Disconnected"}</span></div>
          <dl className="signals"><div><dt>Requests / min</dt><dd>{number(service.request_rate_per_minute, "")}</dd></div>
            <div><dt>5xx errors</dt><dd>{number(service.error_rate_percent, "%")}</dd></div>
            <div><dt>Latency p95</dt><dd>{number(service.latency_p95_ms, " ms")}</dd><small>Bucket-approximated</small></div>
            <div><dt>Uptime probe</dt><dd>{service.availability === null ? "Unknown" : service.availability ? "Passing" : "Failing"}</dd></div></dl>
          <div className="collection-row"><p><strong>Collection:</strong> {collection}</p>
            <p className="muted">Last seen: {service.last_seen_at ? <time dateTime={service.last_seen_at}>{new Date(service.last_seen_at).toLocaleString()}</time> : service.collection_status === "unavailable" ? "Unknown" : "No recent samples"}</p></div>
          {unknown || stale ? <p className="muted">Application health is unknown. Any values above are from the last update.</p> :
            service.reasons.length > 0 ? <ul className="health-reasons">{service.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> :
              <p className="muted">Recent request signals are below the configured health thresholds.{service.availability === null ? " No uptime probe is assigned." : ""}</p>}
        </article>;
      })}</div>
      {update.data && <p className="health-policy muted">Health thresholds: errors ≥ {update.data.policy.error_rate_percent}% or p95 ≥ {update.data.policy.latency_p95_ms} ms over {update.data.policy.window_seconds / 60} minutes. Metrics become stale after {update.data.policy.stale_seconds} seconds. Uptime probes do not measure business health.</p>}
    </>}
  </section>;
}
