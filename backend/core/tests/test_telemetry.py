"""§9.1 of the M2 spec: the observability robustness matrix."""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import structlog
from django.test import Client
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from core.logging import add_trace_context


class _ListHandler(logging.Handler):
    """Spy handler that records rendered messages off the stdlib root logger —
    the same attach point the OTel LoggingHandler uses for OTLP export."""

    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


# ---------- zero-overhead-off (spec 9.1.2) ----------


def test_processor_is_noop_without_active_span():
    """With no active span, the log processor adds NOTHING — off-mode output
    is byte-identical to pre-M2 logs."""
    event = {"event": "hello", "request_id": "r-1"}
    out = add_trace_context(None, "info", dict(event))
    assert out == event  # no trace_id/span_id keys sneak in


def test_disabled_by_default_installs_nothing():
    from annotated_maps.telemetry import _is_initialized, setup_telemetry

    assert setup_telemetry(enabled=False) is False
    assert _is_initialized() is False


# ---------- the join, both directions (spec 9.1.1) ----------


@pytest.fixture()
def memory_otel(monkeypatch):
    """Function-scoped: fully resets global OTel state on teardown so each
    test that uses this fixture gets its own working exporter wired to a
    freshly (re-)initialized tracer provider. Without this reset,
    setup_telemetry's idempotency means only the FIRST test using this
    fixture would ever get real spans."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from annotated_maps.telemetry import _reset_for_tests, setup_telemetry

    # Only span export is injected (in-memory); the log/metric exporters
    # setup_telemetry builds are the real OTLP ones pointed at the default
    # localhost:4318, with nothing listening. Cap their per-flush timeout so
    # teardown's shutdown-flush gives up after one attempt instead of burning
    # ~7s on the exponential connection-refused retry backoff. (monkeypatch
    # auto-restores, and its finalizer runs after this fixture's teardown, so
    # the low timeout is still in effect during _reset_for_tests below.)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TIMEOUT", "1")

    exporter = InMemorySpanExporter()
    setup_telemetry(enabled=True, span_exporter=exporter)
    yield exporter
    exporter.clear()
    _reset_for_tests()


@pytest.mark.django_db
def test_trace_id_joins_span_to_log_line(memory_otel):
    # Capture off the stdlib root logger — the same attach point the OTel
    # LoggingHandler uses — so this exercises the real OTLP export path, not
    # whatever stream structlog happens to write to.
    spy = _ListHandler()
    root = logging.getLogger()
    root.addHandler(spy)
    try:
        client = Client()
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
    finally:
        root.removeHandler(spy)
    trace.get_tracer_provider().force_flush()  # type: ignore[attr-defined]  # drain the BatchSpanProcessor

    spans = memory_otel.get_finished_spans()
    assert spans, "expected at least one span from the request"
    server_span = next(s for s in spans if s.kind.name == "SERVER")
    want_trace_id = format(server_span.get_span_context().trace_id, "032x")

    # the request handler logs at least one structlog line; find one with our trace id
    lines = [json.loads(msg) for msg in spy.messages if msg.startswith("{")]
    joined = [ln for ln in lines if ln.get("trace_id") == want_trace_id]
    assert joined, f"no log line carried trace_id {want_trace_id}"
    assert all("span_id" in ln for ln in joined)


@pytest.mark.django_db
def test_structlog_routes_through_stdlib_for_otlp_export(memory_otel):
    """Regression guard: structlog records must reach the stdlib root logger,
    because that is where the OTel LoggingHandler bridge lives. If structlog is
    ever reconfigured to bypass stdlib (e.g. PrintLoggerFactory), app logs
    would silently stop exporting to Loki — this test fails first."""
    spy = _ListHandler()
    root = logging.getLogger()
    root.addHandler(spy)
    try:
        structlog.get_logger("probe").info("probe_event", k="v")
    finally:
        root.removeHandler(spy)
    assert any("probe_event" in m for m in spy.messages), (
        "structlog must route through stdlib so the OTel LoggingHandler exports it"
    )


@pytest.mark.django_db
def test_span_carries_request_attributes(memory_otel):
    client = Client()
    client.get("/api/v1/health", HTTP_X_REQUEST_ID="req-join-test")
    trace.get_tracer_provider().force_flush()  # type: ignore[attr-defined]  # drain the BatchSpanProcessor
    spans = memory_otel.get_finished_spans()
    server_span = next(s for s in spans if s.kind.name == "SERVER")
    assert server_span.attributes.get("app.request_id") == "req-join-test"


# ---------- OTLP wire test (spec 9.1.3) ----------


class _CapturingHandler(BaseHTTPRequestHandler):
    captured: dict[str, int] = {}

    def do_POST(self):  # noqa: N802 (http.server API)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        type(self).captured[self.path] = len(body)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):  # silence test output
        pass


def test_otlp_exporter_delivers_protobuf_over_http():
    """Local (non-global) providers + the REAL OTLP exporters, pointed at an
    in-process HTTP server: proves the wire mechanics our Grafana Cloud export
    will use for all three signals — traces, metrics, AND logs (spec §9.1.3) —
    with no external service. All three share the one mock receiver."""
    _CapturingHandler.captured = {}
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    tracer_provider = TracerProvider()
    meter_provider = MeterProvider(
        metric_readers=[
            PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=f"{base}/v1/metrics"))
        ]
    )
    logger_provider = LoggerProvider()
    logger_provider.add_log_record_processor(
        SimpleLogRecordProcessor(OTLPLogExporter(endpoint=f"{base}/v1/logs"))
    )
    otel_log_handler = LoggingHandler(logger_provider=logger_provider)
    wire_logger = logging.getLogger("otlp-wire-test")
    wire_logger.setLevel(logging.INFO)
    wire_logger.addHandler(otel_log_handler)
    wire_logger.propagate = False
    try:
        # traces -> /v1/traces
        tracer_provider.add_span_processor(
            SimpleSpanProcessor(OTLPSpanExporter(endpoint=f"{base}/v1/traces"))
        )
        with tracer_provider.get_tracer("wire-test").start_as_current_span("ping"):
            pass
        tracer_provider.force_flush()

        # metrics -> /v1/metrics
        meter_provider.get_meter("wire-test").create_counter("wire_test_pings").add(1)
        meter_provider.force_flush()

        # logs -> /v1/logs (SimpleLogRecordProcessor exports on emit)
        wire_logger.warning("otlp wire-test log line")

        assert _CapturingHandler.captured.get("/v1/traces", 0) > 0
        assert _CapturingHandler.captured.get("/v1/metrics", 0) > 0
        assert _CapturingHandler.captured.get("/v1/logs", 0) > 0
    finally:
        wire_logger.removeHandler(otel_log_handler)
        meter_provider.shutdown()
        logger_provider.shutdown()
        server.shutdown()


# ---------- /metrics gating (spec 9.1.4) ----------


@pytest.mark.django_db
def test_metrics_endpoint_serves_prometheus_exposition():
    client = Client()
    client.get("/api/v1/health")  # generate at least one sample
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "django_http_responses_total_by_status_total" in body


@pytest.mark.django_db
def test_metrics_is_not_reachable_under_api_prefix():
    """The public Ingress routes only /api to this service — mounting outside
    /api is the structural guarantee that /metrics is cluster-internal."""
    client = Client()
    assert client.get("/api/v1/metrics").status_code == 404
    assert client.get("/api/metrics").status_code == 404
