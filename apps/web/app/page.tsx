"use client";

import { FormEvent, useEffect, useState } from "react";
import { api, csrfToken } from "./api-client";
import { HealthPanel } from "./health-panel";

type Project = { id: string; name: string };
type Service = { id: string; project_id: string; name: string; environment: string };

export default function Home() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [signedIn, setSignedIn] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [projectName, setProjectName] = useState("");
  const [serviceName, setServiceName] = useState("");
  const [projectId, setProjectId] = useState("");
  const [environment, setEnvironment] = useState("development");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [demoProbe, setDemoProbe] = useState(false);

  async function refresh() {
    const [p, s] = await Promise.all([api<Project[]>("/projects"), api<Service[]>("/services")]);
    setProjects(p); setServices(s); setRevision((n) => n + 1); setProjectId((current) => current || p[0]?.id || "");
  }

  useEffect(() => {
    api<{ email: string }>("/auth/me").then(() => { setSignedIn(true); return refresh(); })
      .catch(() => setSignedIn(false)).finally(() => setLoading(false));
  }, []);

  async function signIn(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await api("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
      setPassword(""); setSignedIn(true); await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Sign in failed"); }
    finally { setBusy(false); }
  }

  async function addProject(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await api("/projects", { method: "POST", headers: { "X-CSRF-Token": csrfToken() },
        body: JSON.stringify({ name: projectName }) });
      setProjectName(""); await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not create project"); }
    finally { setBusy(false); }
  }

  async function addService(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await api("/services", { method: "POST", headers: { "X-CSRF-Token": csrfToken() },
        body: JSON.stringify({ project_id: projectId, name: serviceName, environment, probe_name: demoProbe ? "demo" : null }) });
      setServiceName(""); await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not create service"); }
    finally { setBusy(false); }
  }

  async function signOut() {
    setBusy(true); setError("");
    try { await api("/auth/logout", { method: "POST", headers: { "X-CSRF-Token": csrfToken() } });
      setSignedIn(false); setProjects([]); setServices([]); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not sign out"); }
    finally { setBusy(false); }
  }

  if (loading) return <main className="center"><p>Checking session…</p></main>;
  if (!signedIn) return <main className="center"><div className="login">
    <p className="mark">OpsDetective</p><h1>Sign in</h1>
    <p className="muted">The incident workspace is ready for its first service.</p>
    <form onSubmit={signIn}><label htmlFor="email">Administrator email</label>
      <input id="email" type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
      <label htmlFor="password">Password</label>
      <input id="password" type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      {error && <p role="alert" className="error">{error}</p>}
      <button disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button></form>
  </div></main>;

  return <div className="shell"><aside><div className="brand"><span className="mark-symbol" aria-hidden="true">◉</span> OpsDetective</div>
    <nav aria-label="Main"><a href="#overview" aria-current="page">Overview</a><a href="#projects">Projects</a><a href="#services">Services</a></nav>
    <button className="quiet" onClick={signOut} disabled={busy}>Sign out</button></aside>
    <main id="overview"><header><div><h1>Overview</h1><p className="muted">Service monitoring workspace</p></div></header>
      {error && <p role="alert" className="error">{error}</p>}
      <section className="summary" aria-label="Workspace summary"><div><span>Projects</span><strong>{projects.length}</strong></div><div><span>Registered services</span><strong>{services.length}</strong></div><div><span>Signal source</span><strong className="source-name">OpenTelemetry</strong></div></section>
      <HealthPanel projects={projects} revision={revision} />
      <div className="columns"><section id="projects"><h2>Projects</h2><p className="muted">Group the services you plan to monitor.</p>
        <form onSubmit={addProject}><label htmlFor="project-name">Project name</label><div className="inline"><input id="project-name" required maxLength={120} value={projectName} onChange={(e) => setProjectName(e.target.value)} /><button disabled={busy}>Add project</button></div></form>
        <ul>{projects.map((p) => <li key={p.id}>{p.name}</li>)}</ul>{projects.length === 0 && <p className="empty">No projects yet. Add one to register a service.</p>}</section>
        <section id="services"><h2>Services</h2><p className="muted">Register a service before connecting its telemetry.</p>
          <form onSubmit={addService}><label htmlFor="service-project">Project</label><select id="service-project" required value={projectId} onChange={(e) => setProjectId(e.target.value)}>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
            <label htmlFor="service-name">Service name</label><input id="service-name" required maxLength={120} value={serviceName} onChange={(e) => setServiceName(e.target.value)} />
            <label htmlFor="environment">Environment</label><input id="environment" required maxLength={64} value={environment} onChange={(e) => setEnvironment(e.target.value)} />
            <label className="checkbox"><input type="checkbox" checked={demoProbe} onChange={(e) => setDemoProbe(e.target.checked)} />Assign the fixed synthetic demo uptime probe</label>
            <button disabled={busy || projects.length === 0}>Add service</button></form>
          <ul>{services.map((s) => <li key={s.id}><span>{s.name}</span><small>{s.environment}</small></li>)}</ul>{services.length === 0 && <p className="empty">No registered services.</p>}</section></div>
    </main></div>;
}
