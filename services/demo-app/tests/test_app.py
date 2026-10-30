import time

from fastapi.testclient import TestClient

import app as demo


def test_orders_faults_and_prometheus_metrics(monkeypatch) -> None:
    monkeypatch.setattr(demo, "TRAFFIC_ENABLED", False)
    monkeypatch.setattr(demo, "FAULTS_ENABLED", False)
    monkeypatch.setattr(demo, "CONTROL_KEY", "test-control-key")
    demo.fault_mode = "off"
    demo.fault_expires_at = 0
    with TestClient(demo.app) as client:
        assert client.get("/healthz").status_code == 200
        normal = client.get("/orders")
        assert normal.status_code == 200
        assert normal.json()["order_id"] == "demo-order-001"
        assert client.post("/internal/faults", json={"mode": "http_500"},
                           headers={"X-Demo-Control-Key": "test-control-key"}).status_code == 404

        monkeypatch.setattr(demo, "FAULTS_ENABLED", True)
        assert client.post("/internal/faults", json={"mode": "http_500"}).status_code == 403
        assert client.post("/internal/faults", json={"mode": "http_500"},
                           headers={"X-Demo-Control-Key": "wrong"}).status_code == 403
        assert client.post("/internal/faults", json={"mode": "http_500", "duration_seconds": 500},
                           headers={"X-Demo-Control-Key": "test-control-key"}).status_code == 422
        control = {"X-Demo-Control-Key": "test-control-key"}
        assert client.post("/internal/faults", json={"mode": "http_500"}, headers=control).status_code == 200
        assert client.get("/orders").status_code == 500
        assert 'demo_requests_total{route="/orders",status="500"}' in client.get("/metrics").text
        demo.fault_expires_at = time.monotonic() - 1
        assert client.get("/orders").status_code == 200

        monkeypatch.setattr(demo, "SLOW_DB_SECONDS", 0.02)
        assert client.post("/internal/faults", json={"mode": "slow_db"}, headers=control).status_code == 200
        started = time.perf_counter()
        assert client.get("/orders").status_code == 200
        assert time.perf_counter() - started >= 0.02
        assert client.post("/internal/faults", json={"mode": "off"}, headers=control).status_code == 200
        assert client.get("/orders").status_code == 200
