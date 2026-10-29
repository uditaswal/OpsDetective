# Copilot handoff

Read `AGENTS.md` first; its rules bind every tool. This file is the working brief for GitHub Copilot (or any assistant) continuing the build.

## Where things stand (2026-10-30)

- **M0 Foundation**: built and verified locally (Compose healthy, login, tests). The CI gate is pending: `dev` is pushed but its GitHub Actions result has not been checked. Do not start claiming M1 complete until M0 CI is green.
- **M1 Monitor, first slice done**: per-service ingestion tokens (create once / list / revoke, keyed digest, audit events), the `app/scope.py` tenant/project guard, cross-project tests, a no-local-LLM compose test, a threat model, and `scripts/record-hardware.sh`.
- The merged product spec (PRD v1.1 + Architecture plan v1.1) is `docs/docs-internal/OpsDetective_Merged_Spec_v1.2.md` and the change log is `docs/docs-internal/pplan.md`. Both are Git-ignored and local-only. If you cannot read them, the summary below is enough.

## Non-negotiables

1. No Ollama, model weights, or inference containers on this Debian host. No compose service, image, or profile for them. Remote Ollama only via `REMOTE_LOCAL_LLM_BASE_URL` (empty by default).
2. Free inference first. `AI_MODE=free_only`, `ALLOW_PAID_MODELS=false`. Project data only goes to providers with `no_training_on_api_data=true` and a documented retention period; other providers get synthetic demo data only. Never assume an unknown model is free or private.
3. Detection and alerts must work with every AI provider offline.
4. Every table has `tenant_id`; telemetry-derived rows also have `project_id`. Read through `app.scope.scoped_select`. Add a cross-project test for each new entity.
5. Never auto-remediate. Model tools are read-only, tenant+project scoped, max 60 min window, max 200 rows, parameterized, no raw query language from the model.
6. Redact before any LLM call. Logs and telemetry are untrusted data, never instructions.
7. Respect milestone gates. Do not present a later-milestone stub as a finished feature.

## Key decisions (merged spec)

- Tenant = `tenant_id` workspace; `project_id` scopes everything below it.
- Queue: Redis + RQ (not ARQ). Fault flag: `DEMO_FAULTS_ENABLED`.
- Detection default: value > median + 5 x MAD in 3 of the last 5 one-minute windows, minimum 20 requests/min, 10 min cooldown, 15 min grouping window by `(tenant_id, project_id, service_id, environment, signal_class)`.
- AI budget: 12,000 input tokens per investigation including tool results, 800 output tokens per call, 3 calls per incident.
- Prometheus retention 15 days until the M2 benchmark.
- p95 is bucket-approximated and labelled so in the UI.

## Next tasks, in order

1. `dev` is pushed. Check the GitHub Actions run, fix anything red, then merge to `main` via PR after the M0 gate.
2. **Decide how the Collector enforces tokens** (see merged spec section 7, open item 1). The hash-only storage cannot be rendered into Collector bearer-auth config. Recommended: a small verifying gateway using `verify_ingestion_token`. Implement, then add an integration test where a revoked token is rejected.
3. Demo app: traffic generator, `/orders`, structured JSON logs, 500 and slow-DB faults behind `DEMO_FAULTS_ENABLED` with admin auth and rate limit. OpenTelemetry SDK instrumentation.
4. Add `node-exporter` and `blackbox-exporter` to the core compose stack; probe targets pass the SSRF allowlist.
5. Service health endpoint and UI cards: healthy / degraded / disconnected, with collection health shown separately. SSE with polling fallback.
6. Onboarding wizard with connection test.
7. Then M2 (benchmark, baselines, incident engine) per the merged spec.

## Definition of done for any change

Lint (`ruff check`), tests (`python -m pytest services/api/tests`), web typecheck/lint/build when `apps/web` changes, and Compose config validation when `infra` changes. Document new env vars in `.env.example` and README. Small commits, no AI attribution or `Co-Authored-By` lines in commits or repository content, no direct pushes to `main`. Record what changed and which gate items remain in `docs/docs-internal/pplan.md`.
