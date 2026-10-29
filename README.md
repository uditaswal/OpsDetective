# OpsDetective

OpsDetective is a self-hostable incident monitoring and investigation platform. It uses OpenTelemetry and Prometheus for collection, then builds explainable baselines and evidence-linked incident reports. The repository is being delivered by milestone; the current implementation is the M0 foundation.

## Current status

M0 provides a Docker Compose stack, a single-administrator API, tenant-scoped project and service records, an audit log, a demo service, a Collector, Prometheus, PostgreSQL, Redis, and a web entry point. Baseline detection, investigations, ingestion-token enforcement, and the full incident UI are planned in later milestones and are not represented as working features here.

## Quick start

Prerequisites: Docker Engine with Compose, 4 GB available memory, and ports 3000 and 4317/4318 free.

1. Copy `.env.example` to `.env` and replace every `change-me` value. Use a long random `SESSION_SECRET` and a private administrator password.
2. Run `docker compose --env-file .env -f infra/docker-compose.yml up --build -d`.
3. Open `http://localhost:3000` and sign in with the administrator credentials from `.env`.
4. Check stack state with `docker compose --env-file .env -f infra/docker-compose.yml ps`.

The API and databases are private to the Compose network. Prometheus scrapes the demo application's `/metrics` endpoint. OTLP ingress is published on ports 4317 and 4318 for local instrumentation experiments; the M0 Collector discards received telemetry until the M1 storage pipeline is implemented. Do not send real customer telemetry to this local demo.

## Development

The API lives in `services/api`, the worker in `services/worker`, the demo app in `services/demo-app`, the web app in `apps/web`, and infrastructure configuration in `infra`. API tests run with `python -m pytest services/api/tests` after installing `services/api/requirements-dev.txt`; run `python -m compileall services` for a dependency-free syntax check. The internal PRD and implementation plan are in `docs/docs-internal`, which is intentionally ignored by Git.

See [foundation architecture](docs/architecture.md) for service boundaries, data flow, and the current trust model.

## Security notes

The local stack is for development. The administrator password and session secret are read from `.env` at runtime and must never be committed. Login sessions use HttpOnly cookies and state-changing requests require a CSRF token. The deployment needs TLS and production ingress controls before it is exposed publicly.
