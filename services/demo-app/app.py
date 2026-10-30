"""Synthetic order traffic and bounded fault scenarios for the local demo."""

import asyncio
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from threading import Lock
from typing import Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from telemetry import DemoTelemetry, configure_telemetry

FAULTS_ENABLED = os.environ.get("DEMO_FAULTS_ENABLED", "false").lower() == "true"
CONTROL_KEY = os.environ.get("DEMO_CONTROL_KEY", "")
INGEST_TOKEN = os.environ.get("DEMO_INGEST_TOKEN", "")
GATEWAY_URL = os.environ.get("DEMO_GATEWAY_URL", "http://gateway:4318").rstrip("/")
TRAFFIC_ENABLED = os.environ.get("DEMO_TRAFFIC_ENABLED", "true").lower() == "true"
TRAFFIC_INTERVAL_SECONDS = float(os.environ.get("DEMO_TRAFFIC_INTERVAL_SECONDS", "2"))
SLOW_DB_SECONDS = 0.75
if not 0.5 <= TRAFFIC_INTERVAL_SECONDS <= 60:
    raise ValueError("DEMO_TRAFFIC_INTERVAL_SECONDS must be between 0.5 and 60")

logger = logging.getLogger("opsdetective.demo")
logger.setLevel(logging.INFO)
logger.propagate = False
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(handler)

requests = Counter("demo_requests_total", "Synthetic demo requests", ["route", "status"])
duration = Histogram("demo_request_duration_seconds", "Synthetic demo request latency",
                     ["route"], buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
fault_mode: Literal["off", "http_500", "slow_db"] = "off"
fault_expires_at = 0.0
fault_lock = Lock()


def log_event(event: str, **fields: str | int | float) -> None:
    logger.info(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "level": "INFO",
                            "service": "opsdetective-demo", "event": event, **fields}, separators=(",", ":")))


async def generate_traffic() -> None:
    async with httpx.AsyncClient(timeout=3) as client:
        while True:
            await asyncio.sleep(TRAFFIC_INTERVAL_SECONDS)
            try:
                await client.get("http://127.0.0.1:8001/orders")
            except httpx.HTTPError:
                log_event("demo.traffic_unavailable")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.telemetry = configure_telemetry(INGEST_TOKEN, GATEWAY_URL)
    task = asyncio.create_task(generate_traffic()) if TRAFFIC_ENABLED else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        app.state.telemetry.shutdown()


app = FastAPI(title="OpsDetective synthetic demo", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def record_order_request(request: Request, call_next):
    if request.url.path != "/orders":
        return await call_next(request)
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed = time.perf_counter() - started
        requests.labels("/orders", str(status_code)).inc()
        duration.labels("/orders").observe(elapsed)
        telemetry: DemoTelemetry = request.app.state.telemetry
        attributes = {"http.route": "/orders", "http.response.status_code": status_code}
        telemetry.request_counter.add(1, attributes)
        telemetry.request_duration.record(elapsed, attributes)
        log_event("demo.order_request", route="/orders", status=status_code,
                  duration_ms=round(elapsed * 1000, 2), trace_id=getattr(request.state, "trace_id", ""))


def active_fault() -> Literal["off", "http_500", "slow_db"]:
    with fault_lock:
        if time.monotonic() >= fault_expires_at:
            return "off"
        return fault_mode


@app.get("/orders")
async def orders(request: Request) -> Response:
    telemetry: DemoTelemetry = request.app.state.telemetry
    with telemetry.tracer.start_as_current_span("GET /orders") as span:
        request.state.trace_id = f"{span.get_span_context().trace_id:032x}"
        mode = active_fault()
        span.set_attribute("demo.fault.mode", mode)
        if mode == "http_500":
            return JSONResponse(status_code=500, content={"detail": "Synthetic server error"})
        if mode == "slow_db":
            await asyncio.sleep(SLOW_DB_SECONDS)
        return JSONResponse({"order_id": "demo-order-001", "status": "confirmed", "total_cents": 2499})


class FaultIn(BaseModel):
    mode: Literal["off", "http_500", "slow_db"]
    duration_seconds: int = Field(default=60, ge=5, le=120)


@app.post("/internal/faults")
def set_fault(body: FaultIn, x_demo_control_key: str | None = Header(default=None)) -> dict[str, str | int]:
    if not FAULTS_ENABLED:
        raise HTTPException(404, "Not found")
    if not CONTROL_KEY or not x_demo_control_key or not secrets.compare_digest(x_demo_control_key, CONTROL_KEY):
        raise HTTPException(403, "Forbidden")
    global fault_mode, fault_expires_at
    with fault_lock:
        fault_mode = body.mode
        fault_expires_at = time.monotonic() + body.duration_seconds if body.mode != "off" else 0.0
    log_event("demo.fault_changed", mode=body.mode, duration_seconds=body.duration_seconds)
    return {"mode": body.mode, "duration_seconds": body.duration_seconds}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
