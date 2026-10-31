import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import health, health_routes
from app.db import Base, get_db, get_session_factory
from app.main import app
from app.models import Admin, LoginSession, Project, Service
from app.schemas import ServiceOut
from app.security import digest, hasher


@pytest.fixture()
def workspace():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    projects = []
    services = []
    with factory() as db:
        db.add(Admin(tenant_id="tenant-a", email="admin@example.invalid",
                     password_hash=hasher.hash("correct-password")))
        for index, tenant in enumerate(("tenant-a", "tenant-a", "tenant-b")):
            project = Project(tenant_id=tenant, name=f"Project {index}")
            db.add(project)
            db.flush()
            service = Service(tenant_id=tenant, project_id=project.id,
                              name=f"Service {index}", environment="test", probe_name="demo")
            db.add(service)
            db.flush()
            projects.append(project.id)
            services.append(service.id)
        db.commit()

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_session_factory] = lambda: factory
    try:
        with TestClient(app) as client:
            client.post("/api/v1/auth/login", json={"email": "admin@example.invalid",
                        "password": "correct-password"}).raise_for_status()
            yield client, factory, projects, services
    finally:
        app.dependency_overrides.clear()
        health_routes.active_streams.clear()
        engine.dispose()


def vector(service_id: str, *, age: int = 1, rate: float = 0.5, errors: float = 0,
           p95: float = 0.02, collector: int = 1, probe: int = 1) -> list[dict]:
    now = time.time()
    data = {"requests": rate, "errors": errors, "p95": p95, "last_seen": now - age}
    rows = [{"metric": {"service_id": service_id, "signal": key}, "value": [now, str(value)]}
            for key, value in data.items()]
    rows.extend({"metric": {"signal": key}, "value": [now, str(value)]}
                for key, value in {"collector": collector, "probe_collector": 1, "probe": probe}.items())
    return rows


def test_health_is_authenticated_and_queries_only_owned_project(workspace, monkeypatch):
    client, _, projects, services = workspace
    queries = []

    def read(query):
        queries.append(query)
        return vector(services[0]) + vector(services[1])[:4] + vector(services[2])[:4]

    monkeypatch.setattr(health, "read_metrics", read)
    with TestClient(app) as anonymous:
        assert anonymous.get(f"/api/v1/services/{services[0]}/health").status_code == 401
        assert anonymous.get(f"/api/v1/projects/{projects[0]}/health/stream").status_code == 401
    assert client.get(f"/api/v1/services/{services[2]}/health").status_code == 404
    assert client.get(f"/api/v1/projects/{projects[2]}/health").status_code == 404
    assert client.get(f"/api/v1/projects/{projects[2]}/health/stream").status_code == 404
    assert queries == []
    result = client.get(f"/api/v1/projects/{projects[0]}/health").json()
    assert [s["id"] for s in result["services"]] == [services[0]]
    assert result["services"][0]["status"] == "healthy"
    assert result["services"][0]["request_rate_per_minute"] == 30
    assert result["services"][0]["latency_p95_ms"] == 20
    assert result["services"][0]["error_rate_percent"] == 0
    assert result["services"][0]["availability"] is True
    assert result["policy"]["window_seconds"] == 120
    assert 'tenant_id="tenant-a"' in queries[0]
    assert f'project_id="{projects[0]}"' in queries[0]
    assert services[1] not in queries[0] and projects[1] not in queries[0]
    assert services[2] not in queries[0]
    own_other = client.get(f"/api/v1/projects/{projects[1]}/health").json()
    assert [s["id"] for s in own_other["services"]] == [services[1]]


@pytest.mark.parametrize("changes,status,collection", [
    ({"errors": 0.05}, "degraded", "connected"),
    ({"p95": 0.75}, "degraded", "connected"),
    ({"probe": 0}, "degraded", "connected"),
    ({"age": 90}, "disconnected", "stale"),
    ({"collector": 0}, "disconnected", "unavailable"),
    ({"errors": float("nan")}, "disconnected", "unavailable"),
    ({"rate": 1e308}, "disconnected", "unavailable"),
    ({"p95": 1e308}, "disconnected", "unavailable"),
    ({"rate": 0, "p95": float("nan")}, "disconnected", "connected"),
    ({"age": -60}, "disconnected", "waiting"),
])
def test_health_does_not_conflate_app_failures_and_collection(workspace, monkeypatch, changes, status, collection):
    client, _, _, services = workspace
    monkeypatch.setattr(health, "read_metrics", lambda _: vector(services[0], **changes))
    result = client.get(f"/api/v1/services/{services[0]}/health").json()
    assert result["status"] == status
    assert result["collection_status"] == collection
    assert result["reasons"]
    if collection in ("stale", "unavailable", "waiting"):
        assert result["error_rate_percent"] is None
        assert result["latency_p95_ms"] is None
        assert result["availability"] is None


def test_missing_probe_and_metrics_backend_errors_never_report_healthy(workspace, monkeypatch):
    client, _, _, services = workspace
    rows = vector(services[0])
    rows = [row for row in rows if row["metric"]["signal"] != "probe_collector"]
    monkeypatch.setattr(health, "read_metrics", lambda _: rows)
    assert client.get(f"/api/v1/services/{services[0]}/health").json()["collection_status"] == "unavailable"
    monkeypatch.setattr(health, "read_metrics", lambda _: [])
    assert client.get(f"/api/v1/services/{services[0]}/health").json()["status"] == "disconnected"

    def unavailable(_):
        raise httpx.ConnectError("private backend detail")

    monkeypatch.setattr(health, "read_metrics", unavailable)
    result = client.get(f"/api/v1/services/{services[0]}/health")
    assert result.status_code == 200
    assert result.json()["collection_status"] == "unavailable"
    assert "private backend detail" not in result.text


@pytest.mark.parametrize("body", [
    b"not-json", b'{"status":"error"}',
    b'[]', b'{"status":"success","data":{"resultType":"vector","result":[{}]}}',
    b'{"status":"success","warnings":["partial"],"data":{"resultType":"vector","result":[]}}',
    b"x" * 262145,
])
def test_backend_response_validation(body, monkeypatch):
    def handler(request):
        assert request.url.params["timeout"] == "1s"
        return httpx.Response(200, content=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(health.httpx, "Client", lambda **kwargs: client)
    with pytest.raises(ValueError):
        health.read_metrics("fixed query")


def test_unassigned_probe_stays_unknown_without_hiding_measured_health():
    ref = ServiceOut(id=str(uuid4()), project_id=str(uuid4()), name="API", environment="test")
    values = {"last_seen": time.time(), "requests": 1, "p95": .01}
    result = health.classify(ref, values, {"collector": 1}, datetime.now(timezone.utc), health.policy())
    assert result.status == "healthy"
    assert result.availability is None


def test_sse_rechecks_session_and_releases_stream_after_logout(workspace, monkeypatch):
    client, factory, projects, services = workspace
    monkeypatch.setattr(health, "read_metrics", lambda _: vector(services[0]))
    monkeypatch.setattr(health_routes, "STREAM_INTERVAL_SECONDS", 0)
    token = client.cookies["session_token"]
    key = digest(token)
    lease = health_routes.reserve_stream(key)

    class Connected:
        async def is_disconnected(self):
            return False

    async def consume():
        events = health_routes.health_events(Connected(), factory, token, projects[0], key, lease)
        assert "retry:" in await events.__anext__()
        event = await events.__anext__()
        data = json.loads(event.split("data: ")[1])
        assert [s["id"] for s in data["services"]] == [services[0]]
        with factory() as db:
            db.execute(delete(LoginSession))
            db.commit()
        assert "access-lost" in await events.__anext__()
        with pytest.raises(StopAsyncIteration):
            await events.__anext__()

    asyncio.run(consume())
    assert not health_routes.active_streams
    with pytest.raises(HTTPException) as denied:
        health_routes.stream_snapshot(factory, token, projects[0])
    assert denied.value.status_code == 401


def test_stream_expiry_http_headers_and_connection_limits(workspace, monkeypatch):
    client, factory, projects, services = workspace
    monkeypatch.setattr(health, "read_metrics", lambda _: vector(services[0]))
    monkeypatch.setattr(health_routes, "STREAM_SNAPSHOTS", 1)
    response = client.get(f"/api/v1/projects/{projects[0]}/health/stream")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: health" in response.text
    assert not health_routes.active_streams
    first, second = health_routes.reserve_stream("same"), health_routes.reserve_stream("same")
    with pytest.raises(HTTPException) as limited:
        health_routes.reserve_stream("same")
    assert limited.value.status_code == 429
    health_routes.release_stream("same", first)
    health_routes.release_stream("same", second)
    with factory() as db:
        row = db.get(LoginSession, digest(client.cookies["session_token"]))
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert client.get(f"/api/v1/projects/{projects[0]}/health/stream").status_code == 401
