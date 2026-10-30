# Threat model (M0 baseline)

Scope: the local Compose stack and the API. Update this file whenever a trust boundary changes.

| Asset | Threat | Control | Status |
| --- | --- | --- | --- |
| Administrator session | Theft, CSRF, brute force | HttpOnly SameSite=Lax cookies, keyed digest storage, CSRF header, login rate limit | Implemented |
| Tenant and project data | Cross-tenant or cross-project reads | `tenant_id` on every row, `app/scope.py` guard, `project_id` on telemetry-derived rows, isolation tests | Implemented for current tables; mandatory for every new table |
| Ingestion tokens | Leak from database, reuse after revoke | Shown once, keyed digest stored, revocation checked, audit events | Implemented in API; enforced by the ingest gateway |
| Ingest gateway (4318) | Unauthenticated or revoked-token telemetry | Gateway verifies hashed token via API, 401 otherwise; Collector and gRPC unpublished; client identity headers overwritten; 10 MB body cap | Implemented; identity headers not yet applied to stored records |
| Telemetry and logs | Prompt injection, secrets in logs | Treat as data; redact before any LLM call; CI injection set | Planned (M3) |
| LLM providers | Project data sent to a provider that trains on it | Privacy gate, free allowlist with privacy capabilities, synthetic data for ungated providers | Planned (M3) |
| Host | Docker socket root-equivalence | Socket only in the `dev-docker` profile | Policy |
| Host resources | Local inference exhausting the server | No Ollama or inference services on the Debian host; CI test on the compose file | Implemented (test) |
| Probes | SSRF | Hostname/CIDR allowlist, block loopback and link-local, DNS re-check, no unchecked redirects | Planned (M1) |
| Fault injection | Abuse in deployed environments | `DEMO_FAULTS_ENABLED=false` default, admin auth, rate limit | Planned (M1) |
