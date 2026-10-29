from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

app = FastAPI(title="OpsDetective synthetic demo")
requests = Counter("demo_requests_total", "Synthetic demo requests", ["route", "status"])
duration = Histogram("demo_request_duration_seconds", "Synthetic demo request latency",
                     ["route"], buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))


@app.get("/healthz")
def healthz() -> dict[str, str]:
    with duration.labels("/healthz").time():
        requests.labels("/healthz", "200").inc()
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
