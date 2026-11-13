"""Verify real host summaries and operator assignment in disposable Compose."""

import json
import os
import time
from http.cookiejar import CookieJar
from uuid import uuid4
from urllib.request import HTTPCookieProcessor, Request, build_opener

from app.db import SessionLocal
from app.host_assignment import assign, unassign

opener = build_opener(HTTPCookieProcessor(CookieJar()))


def call(path: str, body: dict | None = None, csrf: str = "") -> dict:
    request = Request("http://localhost:8000/api/v1" + path,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json", "X-CSRF-Token": csrf})
    with opener.open(request, timeout=5) as response:
        return json.load(response)


csrf = call("/auth/login", {"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]})["csrf_token"]
tenant = call("/auth/me")["tenant_id"]
project = call("/projects", {"name": "Host check " + uuid4().hex}, csrf)["id"]
other = call("/projects", {"name": "Unassigned host check " + uuid4().hex}, csrf)["id"]
path = f"/projects/{project}/host"
assert call(path)["status"] == "unassigned"
with SessionLocal() as db:
    assign(db, tenant, project)
try:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        data = call(path)
        if data["status"] == "connected" and data["cpu_usage_percent"] is not None and data["disk_busy_percent"] is not None:
            assert data["host_id"] and data["project_id"] == project
            assert 0 <= data["cpu_usage_percent"] <= 100
            assert 0 <= data["disk_busy_percent"] <= 100
            assert 0 <= data["memory_usage_percent"] <= 100
            assert 0 <= data["memory_used_bytes"] <= data["memory_total_bytes"]
            assert data["last_seen_at"] and data["freshness_seconds"] <= data["stale_seconds"]
            break
        time.sleep(2)
    else:
        raise AssertionError("Fresh CPU, memory and disk activity samples were not available for the assigned host")
    assert call(f"/projects/{other}/host")["status"] == "unassigned"
finally:
    with SessionLocal() as db:
        unassign(db, tenant, project)
assert call(path)["status"] == "unassigned"
print("Compose scoped host CPU/memory/disk activity and operator-assignment check passed")
