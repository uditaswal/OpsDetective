import json
import math
from datetime import datetime, timezone
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.schemas import ServiceOut


class HealthPolicy(BaseModel):
    stale_seconds: int
    error_rate_percent: float
    latency_p95_ms: float
    window_seconds: int = 120


class ServiceHealth(ServiceOut):
    model_config = ConfigDict(from_attributes=True, validate_assignment=True, allow_inf_nan=False)
    status: Literal["healthy", "degraded", "disconnected"] = "disconnected"
    collection_status: Literal["connected", "stale", "unavailable", "waiting"] = "waiting"
    request_rate_per_minute: float | None = None
    error_rate_percent: float | None = None
    latency_p95_ms: float | None = None
    availability: bool | None = None
    last_seen_at: datetime | None = None
    freshness_seconds: float | None = None
    reasons: list[str] = Field(default_factory=list)


class HealthOverview(BaseModel):
    project_id: str
    observed_at: datetime
    policy: HealthPolicy
    services: list[ServiceHealth]


def policy() -> HealthPolicy:
    return HealthPolicy(stale_seconds=settings.health_stale_seconds,
                        error_rate_percent=settings.health_error_rate_percent,
                        latency_p95_ms=settings.health_latency_p95_ms)


def health_query(tenant_id: str, project_id: str, services: list[ServiceOut]) -> str:
    # Values come from authorized records; JSON escaping also quotes PromQL strings.
    ids = "|".join(service.id for service in services)
    selector = (f'job="otlp",tenant_id={json.dumps(tenant_id)},'
                f'project_id={json.dumps(project_id)},service_id=~{json.dumps(ids)}')
    counter = f"demo_http_requests_total{{{selector}}}"
    expressions = {
        "requests": f"sum by (service_id) (rate({counter}[2m]))",
        "errors": f'sum by (service_id) (rate(demo_http_requests_total{{{selector},http_response_status_code=~"5.."}}[2m]))',
        "p95": f"histogram_quantile(0.95, sum by (service_id, le) (rate(demo_http_duration_seconds_bucket{{{selector}}}[2m])))",
        "last_seen": f"max by (service_id) (max_over_time(timestamp({counter})[5m:15s]))",
        "collector": 'up{job="otlp",instance="collector:8889",tenant_id="",project_id="",service_id=""}',
    }
    if any(service.probe_name == "demo" for service in services):
        probe = 'job="demo-availability",instance="demo-app-health",tenant_id="",project_id="",service_id=""'
        expressions["probe"] = f"probe_success{{{probe}}}"
        expressions["probe_collector"] = f"up{{{probe}}}"
    return " or ".join(f'label_replace(({value}), "signal", "{key}", "", "")'
                       for key, value in expressions.items())


def read_metrics(query: str) -> list[dict]:
    with httpx.Client(timeout=1.5, follow_redirects=False, trust_env=False) as client:
        with client.stream("GET", f"{settings.prometheus_url.rstrip('/')}/api/v1/query",
                           params={"query": query, "timeout": "1s"}) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 262144:
                    raise ValueError("Metric response exceeds limit")
    result = json.loads(body)
    if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
        raise ValueError("Invalid metric response")
    if result.get("status") != "success" or result.get("warnings") or result["data"].get("resultType") != "vector":
        raise ValueError("Metric response is incomplete")
    rows = result["data"].get("result")
    if not isinstance(rows, list) or len(rows) > 504:
        raise ValueError("Invalid metric vector")
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("metric"), dict)
                or not isinstance(row.get("value"), list) or len(row["value"]) != 2):
            raise ValueError("Invalid metric sample")
    return rows


def _values(rows: list[dict], service_id: str, now: float) -> dict[str, float]:
    values = {}
    for row in rows:
        labels = row["metric"]
        if labels.get("service_id", "") != service_id:
            continue
        timestamp, raw = row["value"]
        value = float(raw)
        if labels.get("signal") == "errors" and not math.isfinite(value):
            raise ValueError("Invalid error-rate signal")
        if not math.isfinite(value) or not 0 <= now - float(timestamp) <= 30:
            continue
        signal = labels.get("signal")
        if signal in values:
            raise ValueError("Duplicate metric signal")
        values[signal] = value
    return values


def classify(service: ServiceOut, values: dict[str, float], infrastructure: dict[str, float],
             now: datetime, thresholds: HealthPolicy) -> ServiceHealth:
    health = ServiceHealth(**service.model_dump())
    last_seen = values.get("last_seen")
    if last_seen is not None and 0 <= now.timestamp() - last_seen <= 300:
        health.last_seen_at = datetime.fromtimestamp(last_seen, timezone.utc)
        health.freshness_seconds = round(now.timestamp() - last_seen, 1)
    if infrastructure.get("collector") != 1:
        health.collection_status = "unavailable"
        health.reasons = ["Metric collection is unavailable; application health is unknown."]
        return health
    if health.last_seen_at is None:
        health.reasons = ["No recent request metrics. Check the service connection and instrumentation."]
        return health
    if health.freshness_seconds > thresholds.stale_seconds:
        health.collection_status = "stale"
        health.reasons = ["Request metrics are stale; application health is unknown."]
        return health
    health.collection_status = "connected"
    requests = values.get("requests")
    errors = values.get("errors", 0)
    p95 = values.get("p95")
    if requests is not None and requests >= 0:
        health.request_rate_per_minute = round(requests * 60, 2)
        if requests > 0 and 0 <= errors <= requests:
            health.error_rate_percent = round(errors / requests * 100, 2)
    if p95 is not None and p95 >= 0:
        health.latency_p95_ms = round(p95 * 1000, 2)
    if service.probe_name == "demo":
        if infrastructure.get("probe_collector") != 1 or infrastructure.get("probe") not in (0, 1):
            health.collection_status = "unavailable"
            health.reasons = ["Uptime probe collection is unavailable; application health is unknown."]
            return health
        health.availability = infrastructure["probe"] == 1
    if health.availability is False:
        health.reasons.append("The configured uptime probe failed.")
    if health.error_rate_percent is not None and health.error_rate_percent >= thresholds.error_rate_percent:
        health.reasons.append("Error rate meets or exceeds the health threshold.")
    if health.latency_p95_ms is not None and health.latency_p95_ms >= thresholds.latency_p95_ms:
        health.reasons.append("Latency p95 meets or exceeds the health threshold.")
    if health.reasons:
        health.status = "degraded"
    elif health.error_rate_percent is None or health.latency_p95_ms is None:
        health.reasons = ["Waiting for enough recent requests to assess application health."]
    else:
        health.status = "healthy"
    return health


def snapshot(tenant_id: str, project_id: str, services: list[ServiceOut]) -> HealthOverview:
    now = datetime.now(timezone.utc)
    overview = HealthOverview(project_id=project_id, observed_at=now, policy=policy(), services=[])
    if not services:
        return overview
    try:
        rows = read_metrics(health_query(tenant_id, project_id, services))
        now = datetime.now(timezone.utc)
        overview.observed_at = now
        infrastructure = _values(rows, "", now.timestamp())
        for service in services:
            values = _values(rows, service.id, now.timestamp())
            overview.services.append(classify(service, values, infrastructure, now, overview.policy))
    except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError):
        overview.services = [ServiceHealth(**service.model_dump(), collection_status="unavailable",
                             reasons=["Metrics could not be read. Application health is unknown."])
                             for service in services]
    return overview
