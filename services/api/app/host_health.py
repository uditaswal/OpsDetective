import math
from datetime import datetime, timezone
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import settings
from app.health import read_metrics

SELECTOR = 'job="node-exporter",instance="node-exporter:9100",tenant_id="",project_id="",service_id=""'
HOST_QUERY = " or ".join(
    f'label_replace(({expression}), "signal", "{signal}", "", "")'
    for signal, expression in {
        "cpu": f'100 * (1 - avg(rate(node_cpu_seconds_total{{{SELECTOR},mode="idle"}}[2m])))',
        "total": f"max(node_memory_MemTotal_bytes{{{SELECTOR}}})",
        "available": f"max(node_memory_MemAvailable_bytes{{{SELECTOR}}})",
        "up": f"up{{{SELECTOR}}}",
        "last_seen": f"max(max_over_time(timestamp(node_memory_MemTotal_bytes{{{SELECTOR}}})[5m:15s]))",
    }.items()
)


class HostHealth(BaseModel):
    model_config = ConfigDict(validate_assignment=True, allow_inf_nan=False)
    project_id: str
    host_id: str | None = None
    status: Literal["unassigned", "connected", "waiting", "stale", "unavailable"] = "unassigned"
    observed_at: datetime
    last_seen_at: datetime | None = None
    freshness_seconds: float | None = None
    stale_seconds: int
    cpu_usage_percent: float | None = Field(default=None, ge=0, le=100)
    memory_usage_percent: float | None = Field(default=None, ge=0, le=100)
    memory_total_bytes: int | None = Field(default=None, gt=0)
    memory_used_bytes: int | None = Field(default=None, ge=0)
    detail: str = "No monitoring host is assigned to this project. Ask the deployment operator to assign it."


def host_snapshot(project_id: str, host_id: str) -> HostHealth:
    now = datetime.now(timezone.utc)
    result = HostHealth(project_id=project_id, host_id=host_id, observed_at=now,
                        stale_seconds=settings.health_stale_seconds, status="unavailable",
                        detail="Host collection is unavailable; resource usage is unknown.")
    try:
        rows = read_metrics(HOST_QUERY)
        now = datetime.now(timezone.utc)
        result.observed_at = now
        values: dict[str, float] = {}
        for row in rows:
            signal = row["metric"].get("signal")
            timestamp, raw = row["value"]
            value = float(raw)
            if signal not in {"cpu", "total", "available", "up", "last_seen"} or signal in values:
                raise ValueError("Unexpected host signal")
            if not 0 <= now.timestamp() - float(timestamp) <= 30:
                continue
            if not math.isfinite(value):
                if signal == "cpu":
                    continue
                raise ValueError("Invalid host signal")
            values[signal] = value
        seen = values.get("last_seen")
        if seen is not None and 0 <= now.timestamp() - seen <= 300:
            result.last_seen_at = datetime.fromtimestamp(seen, timezone.utc)
            result.freshness_seconds = round(now.timestamp() - seen, 1)
        if values.get("up") != 1:
            return result
        if result.last_seen_at is None:
            result.status = "waiting"
            result.detail = "Waiting for host memory samples. Check the exporter connection."
            return result
        if result.freshness_seconds > settings.health_stale_seconds:
            result.status = "stale"
            result.detail = "Host samples are stale; resource usage is unknown."
            return result
        total, available = values.get("total"), values.get("available")
        if total is None or available is None or not 0 < total <= 1e18 or not 0 <= available <= total:
            return result
        cpu = values.get("cpu")
        if cpu is not None and not 0 <= cpu <= 100:
            return result
        result.memory_total_bytes = int(total)
        result.memory_used_bytes = int(total - available)
        result.memory_usage_percent = round(100 * (total - available) / total, 1)
        result.cpu_usage_percent = round(cpu, 1) if cpu is not None else None
        result.status = "connected"
        result.detail = ("Whole monitoring host usage, including other processes. CPU uses a two-minute average."
                         if cpu is not None else "Memory samples are fresh. Waiting for enough CPU samples for a two-minute average.")
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError, ValidationError):
        result = HostHealth(project_id=project_id, host_id=host_id, observed_at=now,
                            stale_seconds=settings.health_stale_seconds, status="unavailable",
                            detail="Host collection is unavailable; resource usage is unknown.")
    return result
