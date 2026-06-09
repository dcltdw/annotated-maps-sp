import uuid
from collections.abc import Callable

import structlog
from django.http import HttpRequest, HttpResponse


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
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            tenant_id=getattr(request, "tenant_id", None),
            user_id=getattr(request, "user_id", None),
        )
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        return response
