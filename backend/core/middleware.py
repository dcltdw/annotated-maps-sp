import uuid
from collections.abc import Callable

import structlog
from django.http import HttpRequest, HttpResponse
from opentelemetry import trace

logger = structlog.get_logger(__name__)


class SecurityHeadersMiddleware:
    """Baseline security headers. CSP is locked down; loosen per-route when the SPA needs it."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        return response


class ObservabilityMiddleware:
    """Binds request/tenant/user IDs into the structlog contextvars for every log line."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        tenant_id = getattr(request, "tenant_id", None)
        user_id = getattr(request, "user_id", None)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        span = trace.get_current_span()
        span.set_attribute("app.request_id", request_id)
        if tenant_id:
            span.set_attribute("app.tenant_id", str(tenant_id))
        if user_id:
            span.set_attribute("app.user_id", str(user_id))
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        # Access logging is part of "observability on": only emit when there is a
        # valid span (i.e. OTEL enabled → DjangoInstrumentor installed a server
        # span). OTEL off → no span → no line → log output byte-identical to
        # pre-M2. When on, this line carries trace_id via add_trace_context and
        # routes through stdlib to the OTel LoggingHandler for OTLP→Loki export.
        if span.get_span_context().is_valid:
            logger.info(
                "http_request",
                method=request.method,
                path=request.path,
                status_code=response.status_code,
            )
        return response
