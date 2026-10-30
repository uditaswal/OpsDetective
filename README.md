# OpsDetective

OpsDetective is a self-hostable incident monitoring and investigation platform. It uses OpenTelemetry and Prometheus for collection, then builds explainable baselines and evidence-linked incident reports. The repository is being delivered by milestone; M0 is complete and M1 is in progress.

## Current status

M0 provides a Docker Compose stack, a single-administrator API, tenant-scoped project and service records, an audit log, a demo service, a Collector, Prometheus, PostgreSQL, Redis, and a web entry point. The first M1 slice adds create-once ingestion tokens and an authenticated OTLP/HTTP gateway with revocation. The Collector currently discards received telemetry. Golden-signal storage, service health, baseline detection, investigations, and the full incident UI are not yet implemented.

## Quick start

Prerequisites: Docker Engine with Compose, 4 GB available memory, and ports 3000 and 4318 free.

1. Copy `.env.example` to `.env` and replace every `change-me` value. Use a long random `SESSION_SECRET` and a private administrator password.
2. Run `docker compose --env-file .env -f infra/docker-compose.yml up --build -d`.
3. Open `http://localhost:3000` and sign in with the administrator credentials from `.env`.
4. Check stack state with `docker compose --env-file .env -f infra/docker-compose.yml ps`.

The API and databases are private to the Compose network. Prometheus scrapes the demo application's `/metrics` endpoint. OTLP/HTTP ingress is published on port 4318 through the token-checking gateway; the Collector still discards received telemetry until the M1 storage pipeline is implemented. Do not send real customer telemetry to this local demo.

## Development

The API lives in `services/api`, the worker in `services/worker`, the demo app in `services/demo-app`, the web app in `apps/web`, and infrastructure configuration in `infra`. API tests run with `python -m pytest services/api/tests` after installing `services/api/requirements-dev.txt`; run `python -m compileall services` for a dependency-free syntax check. The internal PRD and implementation plan are in `docs/docs-internal`, which is intentionally ignored by Git.

See [foundation architecture](docs/architecture.md) for service boundaries, data flow, and the current trust model.

## Host hardware

Run `scripts/record-hardware.sh` on the target server and record the output here before claiming any hardware minimum. Recorded on the development machine on 2026-10-30: Intel Core i3-5005U (4 threads), 3.7 GiB RAM, about 786 GB free disk, Linux 6.12 (Debian). This host must not run local LLM inference; all model calls go to cloud APIs or an optional remote workstation. A core-profile benchmark is due in M2.

## Ingestion tokens

`POST /api/v1/services/{id}/tokens` returns a token once; only a keyed digest is stored. `GET` lists metadata and `DELETE /api/v1/services/{id}/tokens/{token_id}` revokes. OTLP/HTTP ingest goes through the authenticated gateway on `127.0.0.1:4318` (`Authorization: Bearer <token>`); requests with missing, wrong or revoked tokens get 401 and never reach the Collector. Revocation takes effect within `TOKEN_CACHE_SECONDS` (default 15). The Collector is not published and OTLP/gRPC (4317) is not exposed. Set `INTERNAL_API_KEY` in `.env`.

CI exercises token creation, accepted ingestion, revocation, and rejection after the gateway cache window against a temporary Compose stack. It generates disposable credentials with `scripts/create-test-env.sh`, then runs `docker compose --env-file <temporary-env-file> -f infra/docker-compose.yml -p opsdetective-ci exec -T api python - < scripts/compose-revocation.py` after the API, Collector, and gateway are healthy.

## Security notes

The local stack is for development. The administrator password and session secret are read from `.env` at runtime and must never be committed. Login sessions use HttpOnly cookies and state-changing requests require a CSRF token. The deployment needs TLS and production ingress controls before it is exposed publicly.
