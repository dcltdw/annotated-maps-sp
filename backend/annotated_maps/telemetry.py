"""Env-gated OpenTelemetry setup (M2 spec §2; ADR-0008).

Direct OTLP/HTTP export from the process — endpoint/auth are pure env config
(OTEL_EXPORTER_OTLP_ENDPOINT / _HEADERS, read by the SDK). Disabled (the
default) installs nothing. Gunicorn runs without --preload, so per-worker
init after fork is safe for the batch-export threads.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

_initialized = False

# Test-only bookkeeping: the LoggingHandler we install on the root logger and
# the providers we create, so _reset_for_tests() can tear them down cleanly
# (stop background export threads, remove the handler) instead of leaking
# them across test runs.
_logging_handler: logging.Handler | None = None
_providers: list[Any] = []


def _is_initialized() -> bool:
    return _initialized


def setup_telemetry(
    *,
    enabled: bool,
    endpoint: str | None = None,
    service_name: str = "annotated-maps-api",
    deploy_env: str = "local",
    span_exporter=None,
    log_exporter=None,
    metric_reader=None,
) -> bool:
    """Initialize tracing, metrics, and log export. Idempotent; returns True
    only on the call that performed initialization."""
    global _initialized, _logging_handler
    if not enabled or _initialized:
        return False

    from opentelemetry import metrics, trace
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({"service.name": service_name, "deployment.environment": deploy_env})

    # Build a real OTLP exporter only when no override is injected — the `or`
    # short-circuits, so an injected test exporter no longer eagerly constructs
    # (and starts) a live OTLPExporter alongside it (#107).
    tracer_provider = TracerProvider(resource=resource)
    span_exporter = span_exporter or (
        OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces") if endpoint else OTLPSpanExporter()
    )
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    reader = metric_reader or PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics") if endpoint else OTLPMetricExporter()
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    log_exporter = log_exporter or (
        OTLPLogExporter(endpoint=f"{endpoint}/v1/logs") if endpoint else OTLPLogExporter()
    )
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    set_logger_provider(logger_provider)
    handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)
    _logging_handler = handler
    _providers.extend([tracer_provider, meter_provider, logger_provider])

    DjangoInstrumentor().instrument()
    PsycopgInstrumentor().instrument(skip_dep_check=True)

    _initialized = True
    return True


def _reset_for_tests() -> None:
    """Test-only: fully undo global OTel/instrumentation state so a later
    setup_telemetry(enabled=True, ...) call re-initializes cleanly with a
    fresh exporter. Not used by production code paths.

    Shuts down the providers created by the call being reset (stopping their
    background export threads), removes the root-logger handler it added,
    un-instruments Django/psycopg, and rewinds OTel's internal "set once"
    globals so the next set_tracer_provider()/set_logger_provider() actually
    takes effect instead of silently no-op-ing against stale globals.
    """
    global _initialized, _logging_handler

    from opentelemetry import _logs, trace
    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    from opentelemetry.metrics import _internal as metrics_internal

    if DjangoInstrumentor().is_instrumented_by_opentelemetry:
        DjangoInstrumentor().uninstrument()
    if PsycopgInstrumentor().is_instrumented_by_opentelemetry:
        PsycopgInstrumentor().uninstrument()

    if _logging_handler is not None:
        logging.getLogger().removeHandler(_logging_handler)
        _logging_handler = None

    # Bound the shutdown timeout: with no real OTLP endpoint listening (the
    # common test case), the underlying exporters retry with backoff before
    # giving up. Calling shutdown() at all — even one that times out — is
    # what matters: it unregisters the provider's atexit hook, so we don't
    # pay for that retry again (invisibly, after streams are closed) at
    # interpreter exit. A short bound here just keeps test teardown snappy;
    # any exporter thread still finishing up runs harmlessly in the
    # background against the rest of the (long) test session.
    for provider in _providers:
        shutdown = getattr(provider, "shutdown", None)
        if shutdown is None:
            continue
        try:
            if "timeout_millis" in inspect.signature(shutdown).parameters:
                shutdown(timeout_millis=1000)
            else:
                shutdown()
        except Exception:  # noqa: BLE001 — best-effort cleanup, never fail a test on this
            pass
    _providers.clear()

    # Rewind the "set once" guards so a later set_tracer_provider() /
    # set_logger_provider() / set_meter_provider() call actually installs
    # the new provider rather than warning and no-op-ing.
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER = None

    _logs._internal._LOGGER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    _logs._internal._LOGGER_PROVIDER = None

    metrics_internal._METER_PROVIDER_SET_ONCE._done = False
    metrics_internal._METER_PROVIDER = None

    _initialized = False
