import logging

import structlog


def add_trace_context(logger, method_name, event_dict):
    """Inject the active OTel trace/span ids. No active span → adds nothing,
    so OTEL-off log output is byte-identical to pre-M2 (M2 spec §9.1.2)."""
    from opentelemetry import trace

    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            add_trace_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        # Route through stdlib logging: the OTel LoggingHandler (telemetry.py)
        # attaches to the stdlib root logger, so structlog records must pass
        # through stdlib for OTLP→Loki export to see them.
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=logging.INFO)
