"""Verify synthetic traffic and authenticated fault control in Compose CI."""

import json
import os
import time
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

API = "http://localhost:8000"
DEMO = "http://demo-app:8001"
PROMETHEUS = "http://prometheus:9090"
opener = build_opener(HTTPCookieProcessor(CookieJar()))


def request(url: str, body: dict | None = None, csrf: str = "") -> tuple[int, dict | str]:
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    req = Request(url, data=json.dumps(body).encode() if body is not None else None,
                  method="POST" if body is not None else "GET", headers=headers)
    try:
        with opener.open(req, timeout=5) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if "json" in response.headers.get("Content-Type", "") else raw
    except HTTPError as error:
        return error.code, {}


def main() -> None:
    status, login = request(f"{API}/api/v1/auth/login", {
        "email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]})
    assert status == 200, f"admin login returned {status}"
    csrf = login["csrf_token"]

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status, metrics = request(f"{DEMO}/metrics")
        if status == 200 and 'demo_requests_total{route="/orders",status="200"}' in metrics:
            break
        time.sleep(1)
    else:
        raise AssertionError("synthetic order traffic was not recorded")

    query = urlencode({"query": 'demo_requests_total{route="/orders",status="200"}'})
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status, result = request(f"{PROMETHEUS}/api/v1/query?{query}")
        if status == 200 and result["data"]["result"]:
            break
        time.sleep(1)
    else:
        raise AssertionError("Prometheus did not scrape the synthetic order metric")

    fault_url = f"{API}/api/v1/demo/faults"
    assert request(fault_url, {"mode": "http_500"})[0] == 403, "CSRF protection was bypassed"
    assert request(fault_url, {"mode": "http_500"}, csrf)[0] == 200
    assert request(f"{DEMO}/orders")[0] == 500

    assert request(fault_url, {"mode": "slow_db"}, csrf)[0] == 200
    started = time.monotonic()
    assert request(f"{DEMO}/orders")[0] == 200
    assert time.monotonic() - started >= 0.7, "slow database fixture did not add latency"

    assert request(fault_url, {"mode": "off"}, csrf)[0] == 200
    assert request(f"{DEMO}/orders")[0] == 200
    print("Compose synthetic demo check passed")


if __name__ == "__main__":
    main()
