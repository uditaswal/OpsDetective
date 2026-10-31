"""Verify stored OTLP identity across projects and tenants using synthetic metrics."""

import json
import os
import time
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4

API = "http://localhost:8000"
PROMETHEUS = "http://prometheus:9090"
METRIC = "opd_identity_check"
opener = build_opener(HTTPCookieProcessor(CookieJar()))


def call(url: str, body: dict | None = None, headers: dict | None = None,
         method: str | None = None) -> dict:
    req = Request(url, data=json.dumps(body).encode() if body is not None else None,
                  headers={"Content-Type": "application/json", **(headers or {})}, method=method)
    with opener.open(req, timeout=10) as response:
        return json.load(response)


def payload(marker: str, value: int, forged: dict[str, str]) -> dict:
    attrs = [{"key": key, "value": {"stringValue": val}} for key, val in forged.items()]
    return {"resourceMetrics": [{
        "resource": {"attributes": attrs},
        "scopeMetrics": [{"metrics": [{"name": METRIC, "gauge": {"dataPoints": [{
            "asInt": str(value), "timeUnixNano": str(time.time_ns()),
            "attributes": [*attrs, {"key": "check_id", "value": {"stringValue": marker}}],
        }]}}]}],
    }]}


def query(marker: str) -> list[dict]:
    result = call(f"{PROMETHEUS}/api/v1/query?" + urlencode({
        "query": f'{METRIC}{{check_id="{marker}"}}'}))
    return result["data"]["result"]


def main() -> None:
    csrf = call(f"{API}/api/v1/auth/login", {"email": os.environ["ADMIN_EMAIL"],
                "password": os.environ["ADMIN_PASSWORD"]})["csrf_token"]
    headers = {"X-CSRF-Token": csrf}
    marker = uuid4().hex
    created = []
    try:
        for index in range(2):
            project = call(f"{API}/api/v1/projects", {"name": f"Metric scope {marker} {index}"}, headers)
            service = call(f"{API}/api/v1/services", {"project_id": project["id"],
                           "name": "Synthetic scope", "environment": "test"}, headers)
            token = call(f"{API}/api/v1/services/{service['id']}/tokens", {}, headers)
            created.append((service, token))
        for index, (service, token) in enumerate(created):
            other = created[1 - index][0]
            forged = {"tenant_id": "foreign-tenant", "project_id": other["project_id"],
                      "service_id": other["id"], "tenant.id": "foreign-tenant",
                      "project.id": other["project_id"], "opd.tenant.id": "foreign-tenant",
                      "tenant-id": "foreign-tenant", "project/id": other["project_id"]}
            call("http://gateway:4318/v1/metrics", payload(marker, index + 1, forged), {
                "Authorization": f"Bearer {token['token']}", "x-opd-tenant-id": "foreign-tenant",
                "x-opd-project-id": other["project_id"], "x-opd-service-id": other["id"],
            })
        # Even a private direct write without authenticated identity must not survive.
        call("http://collector:4318/v1/metrics", payload(marker, 99, {"tenant_id": "forged"}))
        tenant_id = call(f"{API}/api/v1/auth/me")["tenant_id"]
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            rows = query(marker)
            if len(rows) >= 2:
                break
            time.sleep(2)
        else:
            raise AssertionError("both project metrics were not stored within 45 seconds")
        assert len(rows) == 2, "unexpected extra metric identity"
        for index, (service, _) in enumerate(created):
            matching = [row for row in rows if row["metric"].get("project_id") == service["project_id"]]
            assert len(matching) == 1
            row = matching[0]
            assert row["metric"]["tenant_id"] == tenant_id
            assert row["metric"]["service_id"] == service["id"]
            assert row["value"][1] == str(index + 1), "cross-project metric contamination"
            assert not any(key.startswith("opd_") for key in row["metric"])
        print("OTLP metrics stored with server identity; cross-project and tenant spoofing rejected")
    finally:
        for service, token in created:
            call(f"{API}/api/v1/services/{service['id']}/tokens/{token['id']}",
                 headers=headers, method="DELETE")


if __name__ == "__main__":
    main()
