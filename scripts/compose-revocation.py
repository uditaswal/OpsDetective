"""Exercise ingestion token revocation against the running Compose services.

Run inside the API container so the test uses the private service network and
the administrator credentials already supplied to that container.
"""

import json
import os
import time
import uuid
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

API = "http://localhost:8000"
GATEWAY = "http://gateway:4318"
opener = build_opener(HTTPCookieProcessor(CookieJar()))


def post(url: str, body: dict[str, object], headers: dict[str, str] | None = None) -> tuple[int, dict]:
    request = Request(url, data=json.dumps(body).encode(), method="POST",
                      headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with opener.open(request, timeout=5) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, {}


def ingest(token: str | None) -> int:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"{GATEWAY}/v1/metrics", data=b'{"resourceMetrics":[]}',
                      method="POST", headers=headers)
    try:
        with opener.open(request, timeout=5) as response:
            return response.status
    except HTTPError as error:
        return error.code


def revoke(service_id: str, token_id: str, csrf: str) -> int:
    request = Request(f"{API}/api/v1/services/{service_id}/tokens/{token_id}",
                      method="DELETE", headers={"X-CSRF-Token": csrf})
    try:
        with opener.open(request, timeout=5) as response:
            return response.status
    except HTTPError as error:
        return error.code


def main() -> None:
    status, login = post(f"{API}/api/v1/auth/login", {
        "email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]})
    assert status == 200, f"admin login returned {status}"
    csrf = login["csrf_token"]
    headers = {"X-CSRF-Token": csrf}
    status, project = post(f"{API}/api/v1/projects", {"name": f"Revocation {uuid.uuid4().hex}"}, headers)
    assert status == 201, f"project creation returned {status}"
    status, service = post(f"{API}/api/v1/services", {
        "project_id": project["id"], "name": "Revocation test", "environment": "ci"}, headers)
    assert status == 201, f"service creation returned {status}"
    status, created = post(f"{API}/api/v1/services/{service['id']}/tokens", {}, headers)
    assert status == 201, f"token creation returned {status}"
    token = created["token"]

    assert ingest(None) == 401, "missing token was accepted"
    assert ingest("opd_invalid") == 401, "invalid token was accepted"
    assert ingest(token) == 200, "valid token was rejected"
    assert revoke(service["id"], created["id"], csrf) == 200, "token revocation failed"

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if ingest(token) == 401:
            print("Compose ingestion revocation check passed")
            return
        time.sleep(1)
    raise AssertionError("revoked token was accepted after the 15-second cache window")


if __name__ == "__main__":
    main()
