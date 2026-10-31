"""OpenTelemetry instruments for synthetic demo requests."""

from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


@dataclass
class DemoTelemetry:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    tracer: trace.Tracer
    request_counter: metrics.Counter
    request_duration: metrics.Histogram

    def shutdown(self) -> None:
        self.meter_provider.shutdown()
        self.tracer_provider.shutdown()


def configure_telemetry(token: str, gateway_url: str) -> DemoTelemetry:
    """Send metrics and traces only when a service ingestion token is configured."""
    resource = Resource.create({"service.name": "opsdetective-demo", "deployment.environment": "demo"})
    tracer_provider = TracerProvider(resource=resource)
    readers = []
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        tracer_provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{gateway_url}/v1/traces", headers=headers, timeout=3)))
        readers.append(PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=f"{gateway_url}/v1/metrics", headers=headers, timeout=3),
            export_interval_millis=10_000))
    meter_provider = MeterProvider(resource=resource, metric_readers=readers, views=[
        View(instrument_name="demo.http.duration", aggregation=ExplicitBucketHistogramAggregation(
            boundaries=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))),
    ])
    meter = meter_provider.get_meter("opsdetective.demo")
    return DemoTelemetry(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        tracer=tracer_provider.get_tracer("opsdetective.demo"),
        request_counter=meter.create_counter("demo.http.requests", unit="{request}"),
        request_duration=meter.create_histogram("demo.http.duration", unit="s"),
    )
