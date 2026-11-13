import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import host_health
from app.host_assignment import assign, unassign
from app.main import app
from app.models import AuditEvent, MonitoredHost
from app.scope import scoped_select


def host_vector(**changes) -> list[dict]:
    now = time.time()
    values = {"cpu": 25, "disk_busy": 12, "total": 8 * 1024**3, "available": 2 * 1024**3,
              "up": 1, "last_seen": now - 1, **changes}
    if values["last_seen"] == "stale":
        values["last_seen"] = now - 90
    elif values["last_seen"] == "future":
        values["last_seen"] = now + 60
    return [{"metric": {"signal": key}, "value": [now, str(value)]}
            for key, value in values.items() if value is not None]


def test_host_is_unavailable_without_explicit_owned_assignment(workspace, monkeypatch):
    client, factory, projects, _ = workspace
    queries = []
    monkeypatch.setattr(host_health, "read_metrics", lambda query: queries.append(query) or host_vector())
    path = f"/api/v1/projects/{projects[0]}/host"
    with TestClient(app) as anonymous:
        assert anonymous.get(path).status_code == 401
    assert client.get(f"/api/v1/projects/{projects[2]}/host").status_code == 404
    result = client.get(path)
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["status"] == "unassigned"
    assert not queries
    with factory() as db:
        host_id = assign(db, "tenant-a", projects[0]).id
    data = client.get(path).json()
    assert data["host_id"] == host_id and data["project_id"] == projects[0]
    assert data["status"] == "connected" and data["cpu_usage_percent"] == 25
    assert data["memory_usage_percent"] == 75
    assert data["disk_busy_percent"] == 12
    assert data["memory_used_bytes"] == 6 * 1024**3
    assert len(queries) == 1 and queries[0] == host_health.HOST_QUERY
    assert client.get(f"/api/v1/projects/{projects[1]}/host").json()["status"] == "unassigned"
    assert client.get(f"/api/v1/projects/{projects[2]}/host").status_code == 404
    assert len(queries) == 1
    assert client.post(path, json={"url": "http://example.invalid"}).status_code == 405


def test_host_assignment_is_operator_only_unique_and_project_scoped(workspace):
    _, factory, projects, _ = workspace
    with factory() as db:
        with pytest.raises(ValueError, match="Project not found"):
            assign(db, "tenant-a", projects[2])
        host_id = assign(db, "tenant-a", projects[0]).id
        assert assign(db, "tenant-a", projects[0]).id == host_id
        with pytest.raises(ValueError, match="already assigned"):
            assign(db, "tenant-a", projects[1])
        with pytest.raises(ValueError, match="already assigned"):
            assign(db, "tenant-b", projects[2])
        with pytest.raises(ValueError, match="not found"):
            unassign(db, "tenant-a", projects[1])
        assert db.scalar(scoped_select(MonitoredHost, "tenant-a", projects[0])).id == host_id
        unassign(db, "tenant-a", projects[0])
        assert db.scalar(scoped_select(MonitoredHost, "tenant-a", projects[0])) is None
        assert assign(db, "tenant-b", projects[2]).project_id == projects[2]
        events = list(db.scalars(scoped_select(AuditEvent, "tenant-a")))
        assert {event.action for event in events} >= {"host.assign", "host.unassign"}


@pytest.mark.parametrize("changes,status", [
    ({"up": 0}, "unavailable"),
    ({"up": None}, "unavailable"),
    ({"last_seen": None}, "waiting"),
    ({"last_seen": "stale"}, "stale"),
    ({"last_seen": "future"}, "waiting"),
    ({"total": 0}, "unavailable"),
    ({"available": -1}, "unavailable"),
    ({"available": 1e20}, "unavailable"),
    ({"cpu": 101}, "unavailable"),
    ({"cpu": -1}, "unavailable"),
    ({"total": float("inf")}, "unavailable"),
])
def test_host_invalid_or_stale_samples_never_show_resource_usage(monkeypatch, changes, status):
    monkeypatch.setattr(host_health, "read_metrics", lambda _: host_vector(**changes))
    result = host_health.host_snapshot("project", "host")
    assert result.status == status
    assert result.cpu_usage_percent is None and result.memory_usage_percent is None
    assert result.disk_busy_percent is None
    assert result.memory_used_bytes is None and result.memory_total_bytes is None


def test_host_cpu_warmup_zero_and_collection_errors(monkeypatch):
    monkeypatch.setattr(host_health, "read_metrics", lambda _: host_vector(cpu=float("nan")))
    warmup = host_health.host_snapshot("project", "host")
    assert warmup.status == "connected" and warmup.cpu_usage_percent is None
    assert warmup.memory_usage_percent == 75
    monkeypatch.setattr(host_health, "read_metrics", lambda _: host_vector(cpu=0, disk_busy=0, available=8 * 1024**3))
    idle = host_health.host_snapshot("project", "host")
    assert idle.status == "connected" and idle.cpu_usage_percent == 0 and idle.memory_usage_percent == 0
    assert idle.disk_busy_percent == 0
    monkeypatch.setattr(host_health, "read_metrics", lambda _: host_vector() * 2)
    assert host_health.host_snapshot("project", "host").status == "unavailable"

    def outage(_):
        raise httpx.ConnectError("Synthetic backend failure")

    monkeypatch.setattr(host_health, "read_metrics", outage)
    assert host_health.host_snapshot("project", "host").status == "unavailable"


@pytest.mark.parametrize("disk_busy", [None, float("nan"), -1, 101])
def test_disk_warmup_or_invalid_value_stays_unknown(monkeypatch, disk_busy):
    monkeypatch.setattr(host_health, "read_metrics", lambda _: host_vector(disk_busy=disk_busy))
    result = host_health.host_snapshot("project", "host")
    assert result.status == "connected" and result.disk_busy_percent is None
    assert result.memory_usage_percent == 75
