"use client";

import { FormEvent, useEffect, useState } from "react";
import { api, ApiError, csrfToken, SESSION_EXPIRED_EVENT } from "./api-client";
import { ServiceSetup } from "./service-setup";
import type { Project, Service } from "./service-types";
import { HealthPanel } from "./health-panel";
import { HostPanel } from "./host-panel";

export default function Home() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [signedIn, setSignedIn] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [projectName, setProjectName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [healthProjectId, setHealthProjectId] = useState("");

  async function refresh() {
    const [p, s] = await Promise.all([api<Project[]>("/projects"), api<Service[]>("/services")]);
    setProjects(p); setServices(s); setRevision((n) => n + 1);
  }

  useEffect(() => {
    api<{ email: string }>("/auth/me").then(() => { setSignedIn(true); return refresh(); })
      .catch((cause) => {
        setSignedIn(false);
        if (!(cause instanceof ApiError && cause.status === 401)) setError("Session check is unavailable. Try signing in again.");
      }).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const expired = () => { setSignedIn(false); setProjects([]); setServices([]); setError("Your session ended. Sign in again."); };
    window.addEventListener(SESSION_EXPIRED_EVENT, expired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, expired);
  }, []);

  async function refreshAfterChange() {
    try { await refresh(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "The record was saved, but the list could not refresh. Reload to see it."); }
  }

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

  async function signOut() {
    setBusy(true); setError("");
    try { await api("/auth/logout", { method: "POST", headers: { "X-CSRF-Token": csrfToken() } });
      setSignedIn(false); setProjects([]); setServices([]); }
    catch (cause) { if (!(cause instanceof ApiError && cause.status === 401)) setError(cause instanceof Error ? cause.message : "Could not sign out"); }
    finally { setBusy(false); }
  }

  if (loading) return <main className="center"><p>Checking session…</p></main>;
  if (!signedIn) return <main className="center"><div className="login">
    <p className="mark">OpsDetective</p><h1>Sign in</h1>
    <p className="muted">Sign in to monitor your services.</p>
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
      <HealthPanel projects={projects} revision={revision} selectedProjectId={healthProjectId} onProjectChange={setHealthProjectId} />
      <HostPanel projectId={projects.some((project) => project.id === healthProjectId) ? healthProjectId : projects[0]?.id ?? ""} />
      <div className="columns"><section id="projects"><h2>Projects</h2><p className="muted">Group the services you plan to monitor.</p>
        <form onSubmit={addProject}><label htmlFor="project-name">Project name</label><div className="inline"><input id="project-name" required maxLength={120} value={projectName} onChange={(e) => setProjectName(e.target.value)} /><button disabled={busy}>Add project</button></div></form>
        <ul>{projects.map((p) => <li key={p.id}>{p.name}</li>)}</ul>{projects.length === 0 && <p className="empty">No projects yet. Add one to register a service.</p>}</section>
        <ServiceSetup projects={projects} services={services} onChanged={refreshAfterChange} onViewHealth={setHealthProjectId} /></div>
    </main></div>;
}
