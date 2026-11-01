"use client";

import { FormEvent, useRef, useState } from "react";
import { api, csrfToken } from "./api-client";
import type { Project, Service } from "./service-types";
import { TokenSetup } from "./token-setup";

export function ServiceSetup({ projects, services, onChanged, onViewHealth }: {
  projects: Project[]; services: Service[]; onChanged: () => Promise<void>;
  onViewHealth: (projectId: string) => void;
}) {
  const [registering, setRegistering] = useState(false);
  const [selected, setSelected] = useState<Service | null>(null);
  const [projectId, setProjectId] = useState("");
  const [projectName, setProjectName] = useState("");
  const [pendingProject, setPendingProject] = useState<Project | null>(null);
  const [name, setName] = useState("");
  const [environment, setEnvironment] = useState("demo");
  const [source, setSource] = useState("demo");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const choices = pendingProject && !projects.some((project) => project.id === pendingProject.id)
    ? [...projects, pendingProject] : projects;
  const selection = projectId || projects[0]?.id || "new";

  function start() {
    setRegistering(true); setSelected(null); setError("");
    requestAnimationFrame(() => heading.current?.focus());
  }

  async function register(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    let target = selection;
    try {
      if (target === "new") {
        const project = await api<Project>("/projects", { method: "POST", headers: { "X-CSRF-Token": csrfToken() },
          body: JSON.stringify({ name: projectName }) });
        target = project.id; setProjectId(project.id); setPendingProject(project);
        await onChanged();
      }
      const service = await api<Service>("/services", { method: "POST", headers: { "X-CSRF-Token": csrfToken() },
        body: JSON.stringify({ project_id: target, name, environment, probe_name: source === "demo" ? "demo" : null }) });
      setSelected(service); setRegistering(false); setName(""); setProjectName("");
      await onChanged();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not register service. Your details are preserved; check them and retry."); }
    finally { setBusy(false); }
  }

  return <section id="services" aria-labelledby="services-heading">
    <div className="setup-title"><div><h2 id="services-heading">Services</h2><p className="muted">Register, connect and verify a service’s request metrics.</p></div>
      {!registering && !selected && <button onClick={start}>Connect a service</button>}</div>
    {(registering || selected) && <ol className="setup-progress" aria-label="Connection setup">
      <li aria-current={registering ? "step" : undefined}>Register service</li>
      <li aria-current={selected ? "step" : undefined}>Connect and verify</li></ol>}
    {registering && <div className="registration"><h3 ref={heading} tabIndex={-1}>Register service</h3>
      <form onSubmit={register}><label htmlFor="setup-project">Project</label>
        <select id="setup-project" value={selection} onChange={(event) => setProjectId(event.target.value)} disabled={busy}>
          {choices.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          <option value="new">Create a new project</option></select>
        {selection === "new" && <><label htmlFor="setup-project-name">New project name</label>
          <input id="setup-project-name" required maxLength={120} value={projectName} onChange={(event) => setProjectName(event.target.value)} disabled={busy} /></>}
        <label htmlFor="setup-source">Telemetry source</label>
        <select id="setup-source" value={source} disabled={busy} onChange={(event) => {
          setSource(event.target.value); setEnvironment(event.target.value === "demo" ? "demo" : "development");
        }}><option value="demo">Included synthetic demo</option><option value="sdk">Your OpenTelemetry SDK</option></select>
        <label htmlFor="setup-name">Service name</label><input id="setup-name" required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} disabled={busy} />
        <label htmlFor="setup-environment">Environment</label><input id="setup-environment" required maxLength={64} pattern="[a-zA-Z0-9_-]+" value={environment} onChange={(event) => setEnvironment(event.target.value)} disabled={busy} />
        {source === "demo" && <p className="muted">The included demo already emits the required metrics. Its fixed uptime probe will be assigned to this service.</p>}
        {error && <p className="error" role="alert">{error}</p>}
        <div className="setup-actions"><button disabled={busy}>{busy ? "Registering…" : "Register and continue"}</button>
          <button className="quiet" type="button" disabled={busy} onClick={() => setRegistering(false)}>Cancel setup</button></div>
      </form></div>}
    {selected && <TokenSetup key={selected.id} service={selected} onClose={() => setSelected(null)} onViewHealth={onViewHealth} />}
    {!selected && !registering && (services.length === 0 ? <p className="empty">No services yet. Connect the synthetic demo or register your SDK.</p> :
      <ul className="service-registry" aria-label="Registered services">{services.map((service) => <li key={service.id}><div><span>{service.name}</span>
        <small>{service.environment} · {projects.find((project) => project.id === service.project_id)?.name ?? "Project"}</small></div>
        <button className="quiet" onClick={() => { setError(""); setSelected(service); }} aria-label={`Set up ${service.name} ${service.environment}`}>Set up connection</button></li>)}</ul>)}
  </section>;
}
