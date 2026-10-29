"""Authenticated OTLP/HTTP ingest gateway.

Verifies each request's bearer token against the API, then forwards the
unmodified OTLP body to the Collector. Identity is passed on as x-opd-* headers
that clients cannot set. gRPC is intentionally not exposed.
"""

import os
import time

import httpx
from fastapi import FastAPI, Request, Response

API_URL = os.environ.get("API_URL", "http://api:8000")
COLLECTOR_URL = os.environ.get("COLLECTOR_URL", "http://collector:4318")
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "")
CACHE_SECONDS = float(os.environ.get("TOKEN_CACHE_SECONDS", "15"))
MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_BYTES", str(10 * 1024 * 1024)))
SIGNALS = {"metrics", "logs", "traces"}
FORWARDED_HEADERS = ("content-type", "content-encoding")

app = FastAPI(title="OpsDetective ingest gateway", docs_url=None, redoc_url=None)
client = httpx.AsyncClient(timeout=10.0)
cache: dict[str, tuple[float, dict[str, str]]] = {}


async def verify(token: str) -> dict[str, str] | None:
    now = time.monotonic()
    hit = cache.get(token)
    if hit and hit[0] > now:
        return hit[1]
    cache.pop(token, None)
    resp = await client.post(f"{API_URL}/internal/v1/ingest/verify", json={"token": token},
                             headers={"X-Internal-Key": INTERNAL_API_KEY})
    if resp.status_code != 200:
        return None
    identity = resp.json()
    if len(cache) > 1024:
        cache.clear()
    cache[token] = (now + CACHE_SECONDS, identity)
    return identity


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/{signal}")
async def ingest(signal: str, request: Request) -> Response:
    if signal not in SIGNALS:
        return Response(status_code=404)
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return Response(status_code=413)
    try:
        identity = await verify(token.strip())
    except httpx.HTTPError:
        return Response(status_code=503)
    if identity is None:
        return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return Response(status_code=413)
    headers = {k: v for k, v in request.headers.items() if k.lower() in FORWARDED_HEADERS}
    headers.update({"x-opd-tenant-id": identity["tenant_id"], "x-opd-project-id": identity["project_id"],
                    "x-opd-service-id": identity["service_id"]})
    try:
        upstream = await client.post(f"{COLLECTOR_URL}/v1/{signal}", content=body, headers=headers)
    except httpx.HTTPError:
        return Response(status_code=502)
    return Response(content=upstream.content, status_code=upstream.status_code,
                    media_type=upstream.headers.get("content-type"))
