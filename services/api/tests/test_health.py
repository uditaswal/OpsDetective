import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app import health, health_routes
from app.main import app
from app.models import LoginSession
from app.schemas import ServiceOut
from app.security import digest


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


def test_connection_requires_auth_csrf_active_token_and_ownership(workspace, monkeypatch):
    client, _, projects, services = workspace
    csrf = client.cookies["csrf_token"]
    headers = {"X-CSRF-Token": csrf}
    path = f"/api/v1/services/{services[0]}/connection-test"
    calls = []
    monkeypatch.setattr(health, "read_metrics", lambda query: calls.append(query) or vector(services[0]))
    with TestClient(app) as anonymous:
        assert anonymous.post(path, json={}).status_code == 401
    assert client.post(path, json={}).status_code == 403
    assert client.post(f"/api/v1/services/{services[2]}/connection-test", json={}, headers=headers).status_code == 404
    assert client.post(path, json={"url": "http://169.254.169.254"}, headers=headers).status_code == 422
    assert client.post(path, json={}, headers=headers).json()["status"] == "waiting"
    assert not calls
    created = client.post(f"/api/v1/services/{services[0]}/tokens", headers=headers)
    assert created.status_code == 201
    connected = client.post(path, json={}, headers=headers).json()
    assert connected["status"] == "connected" and connected["last_seen_at"]
    assert connected["project_id"] == projects[0]
    assert projects[1] not in calls[0] and services[1] not in calls[0]
    assert client.delete(f"/api/v1/services/{services[0]}/tokens/{created.json()['id']}", headers=headers).status_code == 200
    calls.clear()
    assert client.post(path, json={}, headers=headers).json()["status"] == "waiting"
    assert not calls


@pytest.mark.parametrize("rows,expected", [("empty", "waiting"), ("stale", "stale"), ("outage", "unavailable"), ("degraded", "connected")])
def test_connection_checks_received_metrics_not_application_health(workspace, monkeypatch, rows, expected):
    client, _, _, services = workspace
    headers = {"X-CSRF-Token": client.cookies["csrf_token"]}
    assert client.post(f"/api/v1/services/{services[0]}/tokens", headers=headers).status_code == 201
    data = vector(services[0])[4:] if rows == "empty" else vector(services[0], age=90 if rows == "stale" else 1,
            collector=0 if rows == "outage" else 1, errors=.1 if rows == "degraded" else 0)
    monkeypatch.setattr(health, "read_metrics", lambda _: data)
    result = client.post(f"/api/v1/services/{services[0]}/connection-test", json={}, headers=headers)
    assert result.status_code == 200 and result.json()["status"] == expected


def test_connection_and_token_creation_are_rate_limited(workspace, monkeypatch):
    from app import rate_limit
    client, _, _, services = workspace
    headers = {"X-CSRF-Token": client.cookies["csrf_token"]}
    monkeypatch.setattr(health, "read_metrics", lambda _: [])
    for _ in range(10):
        assert client.post(f"/api/v1/services/{services[0]}/tokens", headers=headers).status_code == 201
    assert client.post(f"/api/v1/services/{services[0]}/tokens", headers=headers).status_code == 429
    for _ in range(12):
        assert client.post(f"/api/v1/services/{services[0]}/connection-test", json={}, headers=headers).status_code == 200
    assert client.post(f"/api/v1/services/{services[0]}/connection-test", json={}, headers=headers).status_code == 429
    now = rate_limit.monotonic()
    monkeypatch.setattr(rate_limit, "monotonic", lambda: now + 61)
    assert client.post(f"/api/v1/services/{services[0]}/connection-test", json={}, headers=headers).status_code == 200


def test_registration_strips_names_and_rejects_whitespace(workspace):
    client, _, projects, _ = workspace
    headers = {"X-CSRF-Token": client.cookies["csrf_token"]}
    assert client.post("/api/v1/projects", json={"name": "   "}, headers=headers).status_code == 422
    assert client.post("/api/v1/services", json={"name": "   ", "project_id": projects[0], "environment": "test"}, headers=headers).status_code == 422
    created = client.post("/api/v1/projects", json={"name": "  Trimmed  "}, headers=headers)
    assert created.status_code == 201 and created.json()["name"] == "Trimmed"
