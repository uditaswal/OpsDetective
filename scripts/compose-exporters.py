"""Check host metrics, fixed probes and SSRF rejection inside disposable Compose."""

import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GATEWAY = "http://probe-gateway:9116"


def fetch(url: str, method: str = "GET") -> tuple[int, str]:
    try:
        with urlopen(Request(url, method=method), timeout=10) as response:
            return response.status, response.read().decode()
    except HTTPError as error:
        return error.code, ""


def main() -> None:
    status, metrics = fetch("http://node-exporter:9100/metrics")
    assert status == 200
    for name in ("node_cpu_seconds_total", "node_memory_MemTotal_bytes", "node_load1",
                 "node_disk_read_bytes_total"):
        assert name in metrics, f"missing host metric: {name}"
    status, metrics = fetch(f"{GATEWAY}/probe/demo")
    assert status == 200 and "probe_success 1" in metrics
    assert fetch(f"{GATEWAY}/probe/demo", method="POST")[0] == 405
    for target in ("http://169.254.169.254/latest/meta-data/", "http://postgres:5432",
                   "http://127.0.0.1:9115", "https://example.com",
                   "http://demo-app:8001/healthz"):
        query = urlencode({"target": target})
        assert fetch(f"{GATEWAY}/probe/demo?{query}")[0] == 400
        assert fetch(f"{GATEWAY}/probe?{query}")[0] == 404
    assert fetch(f"{GATEWAY}/probe/demo?module=other")[0] == 400
    assert fetch(f"{GATEWAY}/metrics")[0] == 404
    try:
        fetch("http://probe-gateway:9115/probe?target=http://postgres:5432")
    except URLError:
        pass
    else:
        raise AssertionError("raw blackbox listener is accessible over the network")

    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        ready = True
        for query in ('up{job="node-exporter"}', 'probe_success{job="demo-availability"}'):
            status, body = fetch("http://prometheus:9090/api/v1/query?" + urlencode({"query": query}))
            rows = json.loads(body)["data"]["result"] if status == 200 else []
            ready = ready and bool(rows) and all(row["value"][1] == "1" for row in rows)
        if ready:
            print("Host metrics, allowlisted probe, SSRF rejection and Prometheus scrapes passed")
            return
        time.sleep(2)
    raise AssertionError("exporter signals did not reach Prometheus within 45 seconds")


if __name__ == "__main__":
    main()
