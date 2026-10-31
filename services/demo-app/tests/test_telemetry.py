import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest

from telemetry import configure_telemetry


def test_otel_export_uses_gateway_paths_and_bearer_token() -> None:
    received: list[tuple[str, str, str]] = []
    histograms = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            received.append((self.path, self.headers.get("Authorization", ""),
                             self.headers.get("Content-Type", "")))
            body = self.rfile.read(int(self.headers["Content-Length"]))
            if self.path == "/v1/metrics":
                exported = ExportMetricsServiceRequest.FromString(body)
                for resource in exported.resource_metrics:
                    for scope in resource.scope_metrics:
                        histograms.extend(metric.histogram for metric in scope.metrics
                                          if metric.name == "demo.http.duration")
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        telemetry = configure_telemetry("opd_test_token", f"http://127.0.0.1:{server.server_port}")
        telemetry.request_counter.add(1, {"http.route": "/orders", "http.response.status_code": 200})
        telemetry.request_duration.record(0.01)
        telemetry.request_duration.record(0.75)
        with telemetry.tracer.start_as_current_span("GET /orders"):
            pass
        assert telemetry.meter_provider.force_flush(timeout_millis=5000)
        assert telemetry.tracer_provider.force_flush(timeout_millis=5000)
        telemetry.shutdown()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert {path for path, _, _ in received} == {"/v1/metrics", "/v1/traces"}
    assert all(auth == "Bearer opd_test_token" for _, auth, _ in received)
    assert all(content_type == "application/x-protobuf" for _, _, content_type in received)
    assert histograms
    point = histograms[0].data_points[0]
    assert list(point.explicit_bounds) == [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]
    assert point.count == 2
    assert point.bucket_counts[1] == 1 and point.bucket_counts[7] == 1
