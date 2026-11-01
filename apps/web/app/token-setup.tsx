"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError, csrfToken } from "./api-client";
import type { Connection, CreatedToken, Service, Token } from "./service-types";

type Props = { service: Service; onClose: () => void; onViewHealth: (projectId: string) => void };

export function TokenSetup({ service, onClose, onViewHealth }: Props) {
  const [tokens, setTokens] = useState<Token[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [secretAvailable, setSecretAvailable] = useState(false);
  const [revealedToken, setRevealedToken] = useState("");
  const [copied, setCopied] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [connection, setConnection] = useState<Connection | null>(null);
  const secret = useRef<CreatedToken | null>(null);
  const expires = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const generation = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);

  function forgetSecret() {
    secret.current = null;
    clearTimeout(expires.current);
    setSecretAvailable(false); setRevealedToken(""); setCopied(false);
  }

  useEffect(() => {
    const abort = new AbortController();
    const version = ++generation.current;
    heading.current?.focus();
    api<Token[]>(`/services/${encodeURIComponent(service.id)}/tokens`, { signal: abort.signal })
      .then((rows) => { if (version === generation.current) setTokens(rows); })
      .catch((cause) => { if (!abort.signal.aborted) setError(cause instanceof Error ? cause.message : "Could not read tokens."); })
      .finally(() => { if (version === generation.current) setLoading(false); });
    return () => { generation.current = version + 1; abort.abort(); secret.current = null; clearTimeout(expires.current); };
  }, [service.id]);

  async function refreshTokens() {
    setLoading(true); setError("");
    try { setTokens(await api<Token[]>(`/services/${encodeURIComponent(service.id)}/tokens`)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not read tokens. Retry refresh."); }
    finally { setLoading(false); }
  }

  async function createToken() {
    if (busy || secret.current) return;
    setBusy(true); setError(""); setConnection(null);
    const version = generation.current;
    try {
      const created = await api<CreatedToken>(`/services/${encodeURIComponent(service.id)}/tokens`, {
        method: "POST", headers: { "X-CSRF-Token": csrfToken() },
      });
      if (version !== generation.current) return;
      secret.current = created;
      setTokens((rows) => [{ id: created.id, service_id: created.service_id, prefix: created.prefix,
        created_at: created.created_at, revoked_at: created.revoked_at }, ...rows]);
      setSecretAvailable(true); setRevealedToken(""); setCopied(false);
      expires.current = setTimeout(forgetSecret, 300000);
    } catch (cause) {
      if (version === generation.current) setError(cause instanceof ApiError ? cause.message : "Token response was interrupted. Refresh the token list before trying again.");
    } finally { if (version === generation.current) setBusy(false); }
  }

  async function copyToken() {
    if (!secret.current) return;
    setError("");
    try { await navigator.clipboard.writeText(secret.current.token); setCopied(true); }
    catch { setError("Clipboard access is unavailable. Use Show token to copy it manually, then hide it."); }
  }

  async function revoke(id: string) {
    setBusy(true); setError(""); setConnection(null);
    const version = generation.current;
    try {
      const row = await api<Token>(`/services/${encodeURIComponent(service.id)}/tokens/${encodeURIComponent(id)}`, {
        method: "DELETE", headers: { "X-CSRF-Token": csrfToken() },
      });
      if (version !== generation.current) return;
      setTokens((rows) => rows.map((token) => token.id === id ? row : token));
      if (secret.current?.id === id) forgetSecret();
      setConfirmation("");
    } catch (cause) { if (version === generation.current) setError(cause instanceof Error ? cause.message : "Could not revoke token. Retry the action."); }
    finally { if (version === generation.current) setBusy(false); }
  }

  async function testConnection() {
    setBusy(true); setError("");
    const version = generation.current;
    try {
      const result = await api<Connection>(`/services/${encodeURIComponent(service.id)}/connection-test`, {
        method: "POST", body: "{}", headers: { "X-CSRF-Token": csrfToken() },
      });
      if (version === generation.current) setConnection(result);
    } catch (cause) { if (version === generation.current) setError(cause instanceof Error ? cause.message : "Could not test the connection. Retry when collection is available."); }
    finally { if (version === generation.current) setBusy(false); }
  }

  const active = tokens.some((token) => !token.revoked_at);
  return <div className="token-setup" aria-label="Service connection setup">
    <div className="setup-title"><div><h3 ref={heading} tabIndex={-1}>{service.name}</h3><p className="muted">{service.environment} · Connect telemetry</p></div>
      <button className="quiet" disabled={busy} onClick={onClose}>Close setup</button></div>
    {error && <p className="error" role="alert">{error}</p>}
    <h4>Ingestion token</h4>
    <p className="muted">Create a token for this service and store it with your application secrets. Its full value is available only here, for five minutes. Closing setup or signing out discards it.</p>
    {loading ? <p role="status">Reading tokens…</p> : <>
      <div className="setup-actions"><button disabled={busy || secretAvailable} onClick={createToken}>{busy ? "Working…" : "Create ingestion token"}</button>
        <button className="quiet" disabled={busy} onClick={refreshTokens}>Refresh token list</button></div>
      {secretAvailable && <div className="new-token" aria-label="New token">
        <p><strong>Save this token now.</strong> It cannot be retrieved later.</p>
        <div className="setup-actions"><button disabled={busy} onClick={copyToken}>{copied ? "Token copied" : "Copy new token"}</button>
          <button className="quiet" onClick={() => setRevealedToken((value) => value ? "" : secret.current?.token ?? "")} aria-pressed={!!revealedToken}>{revealedToken ? "Hide token" : "Show token"}</button>
          <button className="quiet" onClick={forgetSecret}>I’ve saved the token</button></div>
        {revealedToken && <p className="secret-value"><code>{revealedToken}</code></p>}
        {copied && <p role="status">Copied. Save it in your private environment file or secret manager.</p>}
      </div>}
      {tokens.length === 0 ? <p className="empty">No ingestion tokens yet.</p> : <ul className="token-list" aria-label="Ingestion tokens">
        {tokens.map((token) => <li key={token.id}><div><strong>{token.prefix}…</strong><span>{token.revoked_at ? "Revoked" : "Active"} · Created {new Date(token.created_at).toLocaleString()}</span></div>
          {!token.revoked_at && (confirmation === token.id ? <div className="revoke-confirmation"><p>Revocation stops new intake after the gateway’s 15-second cache expires.</p>
            <div className="setup-actions"><button disabled={busy} onClick={() => revoke(token.id)}>Confirm revoke</button><button className="quiet" disabled={busy} onClick={() => setConfirmation("")}>Keep token</button></div></div> :
              <button className="quiet" disabled={busy} onClick={() => setConfirmation(token.id)} aria-label={`Revoke token ${token.prefix}`}>Revoke</button>)}</li>)}
      </ul>}
    </>}
    <h4>Configure the SDK</h4>
    {service.probe_name === "demo" ? <><p>For the included synthetic demo, set <code>DEMO_INGEST_TOKEN</code> in your private <code>.env</code> file to the copied value, then recreate the demo:</p>
      <pre><code>docker compose --env-file .env -f infra/docker-compose.yml up -d --no-deps --force-recreate demo-app</code></pre></> : <>
      <p>Configure an OpenTelemetry SDK on the Linux host to export HTTP/protobuf metrics. Replace the token placeholder privately; these instructions never contain the token value.</p>
      <pre><code>{"OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318\nOTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf\nOTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20<INGESTION_TOKEN>"}</code></pre>
      <p className="muted">Current HTTP health instruments: <code>demo.http.requests</code> (monotonic counter) and <code>demo.http.duration</code> (histogram in seconds), with <code>http.route</code> and <code>http.response.status_code</code>. Export every 10–15 seconds.</p>
    </>}
    <h4>Verify received metrics</h4>
    <p className="muted">The test reads fresh request metrics stored for this service. An empty accepted request does not count. Collection can take up to a minute after SDK setup.</p>
    <div className="setup-actions"><button disabled={busy || loading || !active} onClick={testConnection}>{busy ? "Working…" : "Test connection"}</button>
      <a href="#health-heading" onClick={() => onViewHealth(service.project_id)}>View service health</a></div>
    {connection && <div className={`connection-result ${connection.status}`} role="status"><strong>{connection.status === "connected" ? "Telemetry received" : connection.status === "waiting" ? "Waiting for telemetry" : connection.status === "stale" ? "Telemetry is stale" : "Collection unavailable"}</strong>
      <p>{connection.detail}</p><p className="muted">Checked {new Date(connection.checked_at).toLocaleString()}{connection.last_seen_at ? ` · Last seen ${new Date(connection.last_seen_at).toLocaleString()}` : ""}</p></div>}
  </div>;
}
