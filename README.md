# OpsDetective

**A self-hosted observability project with authenticated OpenTelemetry intake and tenant-scoped service administration.**

OpsDetective brings a web interface, API, ingest gateway, OpenTelemetry Collector, Prometheus, PostgreSQL, Redis, and a synthetic demo service together in one Docker Compose stack. The current runnable flow focuses on service setup, access control, and telemetry intake.

## What you can explore

- **Service control plane:** administrator sign-in, project and service registration, tenant-scoped records, and audit events.
- **Authenticated ingest:** create-once service tokens, keyed-digest storage, revocation, and an OTLP/HTTP gateway that verifies each bearer token before forwarding to the private Collector.
- **Synthetic telemetry:** a demo service generates order requests and exposes health and Prometheus metrics without requiring customer data.
- **Operational checks:** GitHub Actions runs Python and web checks, Compose integration, secret scanning, and CodeQL. The integration check exercises token creation, accepted ingest, revocation, and rejection after the gateway cache expires.

## Run locally

Prerequisites: Docker Engine with Compose, about 4 GB of available memory, and free ports 3000 and 4318.

1. Copy `.env.example` to `.env` and replace every `change-me` value with a private value.
2. Start the stack:

   ```bash
   docker compose --env-file .env -f infra/docker-compose.yml up --build -d
   ```

3. Open `http://localhost:3000` and sign in with the administrator credentials from `.env`.
4. Check service health:

   ```bash
   docker compose --env-file .env -f infra/docker-compose.yml ps
   ```

Use synthetic data for the local demonstration. The web interface and OTLP/HTTP gateway bind to loopback; the API, Collector, and data services stay on the private Compose network.

## How it is organized

| Path | Responsibility |
| --- | --- |
| `apps/web` | Next.js interface and same-origin API proxy |
| `services/api` | FastAPI authentication, project and service records, and token lifecycle |
| `services/gateway` | Bearer-token verification and OTLP/HTTP forwarding |
| `services/demo-app` | Synthetic health and Prometheus metrics |
| `services/worker` | RQ worker backed by Redis |
| `infra` | Compose, Collector, and Prometheus configuration |

See the [architecture and data flow](docs/architecture.md) for service boundaries and trust decisions.

## Ingestion token flow

An administrator creates a token for a service through `POST /api/v1/services/{id}/tokens`. The API returns the token once and stores only a keyed digest. Clients send OTLP/HTTP requests to `127.0.0.1:4318` with `Authorization: Bearer <token>`. The gateway verifies the token with the API, stamps the service identity, and forwards accepted requests to the Collector. Revoked tokens are rejected after the gateway's 15-second cache window.

The API requires a session and CSRF token for token creation and revocation. The local `.env` file is excluded from Git and Docker build contexts.
