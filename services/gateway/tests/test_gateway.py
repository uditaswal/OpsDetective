import asyncio
import importlib.util
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

spec = importlib.util.spec_from_file_location("gateway_app", Path(__file__).resolve().parents[1] / "app.py")
gw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gw)

IDENTITY = {"tenant_id": "t", "project_id": "p", "service_id": "s"}


def install(valid: set[str]):
    calls = {"verify": 0, "collector": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/v1/ingest/verify":
            calls["verify"] += 1
            import json
            ok = json.loads(request.content)["token"] in valid
            return httpx.Response(200, json=IDENTITY) if ok else httpx.Response(401)
        calls["collector"].append(request)
        return httpx.Response(200, json={})

    asyncio.run(gw.client.aclose())
    gw.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gw.cache.clear()
    return calls


def test_rejects_missing_wrong_and_revoked_tokens_without_forwarding() -> None:
    calls = install({"opd_good"})
    with TestClient(gw.app) as c:
        assert c.post("/v1/metrics", content=b"x").status_code == 401
        assert c.post("/v1/metrics", content=b"x", headers={"Authorization": "Basic abc"}).status_code == 401
        assert c.post("/v1/metrics", content=b"x", headers={"Authorization": "Bearer opd_bad"}).status_code == 401
    assert calls["collector"] == []


def test_valid_token_forwards_with_server_stamped_identity() -> None:
    calls = install({"opd_good"})
    with TestClient(gw.app) as c:
        r = c.post("/v1/traces", content=b"payload", headers={
            "Authorization": "Bearer opd_good", "Content-Type": "application/x-protobuf",
            "x-opd-project-id": "forged"})
    assert r.status_code == 200
    sent = calls["collector"][0]
    assert sent.headers["x-opd-project-id"] == "p"
    assert "authorization" not in sent.headers
    assert sent.content == b"payload"


def test_unknown_signal_and_oversize_body() -> None:
    install({"opd_good"})
    with TestClient(gw.app) as c:
        assert c.post("/v1/other", headers={"Authorization": "Bearer opd_good"}).status_code == 404
        gw.MAX_BODY_BYTES = 4
        try:
            r = c.post("/v1/logs", content=b"12345", headers={"Authorization": "Bearer opd_good"})
        finally:
            gw.MAX_BODY_BYTES = 10 * 1024 * 1024
        assert r.status_code == 413


def test_revocation_applies_after_cache_expiry() -> None:
    valid = {"opd_good"}
    install(valid)
    with TestClient(gw.app) as c:
        h = {"Authorization": "Bearer opd_good"}
        assert c.post("/v1/logs", content=b"x", headers=h).status_code == 200
        valid.clear()
        assert c.post("/v1/logs", content=b"x", headers=h).status_code == 200  # cached
        gw.cache.clear()  # stands in for TTL expiry
        assert c.post("/v1/logs", content=b"x", headers=h).status_code == 401
