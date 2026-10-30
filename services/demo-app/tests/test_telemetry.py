import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telemetry import configure_telemetry


def test_otel_export_uses_gateway_paths_and_bearer_token() -> None:
    received: list[tuple[str, str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            received.append((self.path, self.headers.get("Authorization", ""),
                             self.headers.get("Content-Type", "")))
            self.rfile.read(int(self.headers["Content-Length"]))
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
