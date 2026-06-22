from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

from core.models import AuthSession, User

SESSION_TTL = timedelta(days=14)


def hash_token(raw: str) -> str:
    """SHA-256 hex of a bearer token. Tokens are 256-bit random, so a fast hash is
    correct (no slow KDF needed — that's for low-entropy passwords)."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _client_ip(request: HttpRequest) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[-1].strip()  # trusted last hop behind the proxy
    return request.META.get("REMOTE_ADDR") or None


def create_session(user: User, request: HttpRequest) -> str:
    """Mint a bearer token, persist only its hash (+ expiry/ip/ua), return the raw token."""
    raw = secrets.token_urlsafe(32)
    AuthSession.objects.create(
        user=user,
        token_hash=hash_token(raw),
        expires_at=timezone.now() + SESSION_TTL,
        created_ip=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
    )
    return raw


def bearer_token(request: HttpRequest) -> str | None:
    header = request.headers.get("Authorization", "")
    prefix = "Bearer "
    return header[len(prefix) :].strip() if header.startswith(prefix) else None


def authed_user(request: HttpRequest) -> User | None:
    """The user behind a valid, non-expired bearer token; None otherwise."""
    token = bearer_token(request)
    if not token:
        return None
    session = (
        AuthSession.objects.filter(token_hash=hash_token(token), expires_at__gt=timezone.now())
        .select_related("user")
        .first()
    )
    return session.user if session else None


@dataclass(frozen=True)
class Identity:
    """The resolved caller identity for a request. `user_id` is the viewer/author id
    (None = guest). `is_authenticated` is True only when resolved from a bearer token
    (vs. an anonymous SANDBOX_MODE `preview_as` persona)."""

    user_id: UUID | None
    is_authenticated: bool


def resolve_identity(request: HttpRequest, preview_as: UUID | None) -> Identity:
    """Resolve who the caller is. An authenticated bearer user ALWAYS wins; otherwise,
    only under SANDBOX_MODE, an anonymous visitor may preview as a persona; else guest.

    This closes the preview_as impersonation hole: `preview_as` is ignored whenever a real
    user is authenticated, and ignored entirely outside SANDBOX_MODE."""
    user = authed_user(request)
    if user is not None:
        return Identity(user_id=user.id, is_authenticated=True)
    if settings.SANDBOX_MODE and preview_as is not None:
        return Identity(user_id=preview_as, is_authenticated=False)
    return Identity(user_id=None, is_authenticated=False)
