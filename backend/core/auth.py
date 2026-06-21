from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

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


def _bearer_token(request: HttpRequest) -> str | None:
    header = request.headers.get("Authorization", "")
    prefix = "Bearer "
    return header[len(prefix) :].strip() if header.startswith(prefix) else None


def authed_user(request: HttpRequest) -> User | None:
    """The user behind a valid, non-expired bearer token; None otherwise."""
    token = _bearer_token(request)
    if not token:
        return None
    session = (
        AuthSession.objects.filter(token_hash=hash_token(token), expires_at__gt=timezone.now())
        .select_related("user")
        .first()
    )
    return session.user if session else None
