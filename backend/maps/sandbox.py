"""Sandbox-mode behaviour for the public demo deploy. Everything here is gated by
settings.SANDBOX_MODE (default False → local dev + tests behave like a normal app)."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone
from ninja.errors import HttpError

from maps.models import Note

# Per-deploy caps (only enforced when SANDBOX_MODE).
MAX_NOTES_PER_SESSION = 15
MAX_APPENDS_PER_SESSION = 30
MAX_CREATES_PER_IP_PER_HOUR = 30
MAX_EPHEMERAL_ROWS = 2000


def client_ip(request: HttpRequest) -> str:
    """Best-effort client IP for the per-IP creation cap.

    Behind Render's single proxy the trustworthy value is the RIGHTMOST
    X-Forwarded-For hop — the IP Render itself appends from the real connection.
    The client can forge leftmost hops, so we must NOT use [0]; we take [-1].
    (Assumes exactly one trusted proxy in front of the app, which is Render's setup.)
    Falls back to REMOTE_ADDR when there is no XFF header (e.g. local/dev)."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "") or ""


def ensure_session(request: HttpRequest) -> str:
    """Return the session key, creating a session row if none exists yet."""
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def is_editable(request: HttpRequest, note: Note, preview_as: UUID | None) -> bool:
    """Whether the caller may edit/delete `note` (drives the read API's `editable`)."""
    if settings.SANDBOX_MODE:
        sk = request.session.session_key
        return (not note.is_seed) and bool(sk) and note.session_key == sk
    return note.author_id == preview_as


def authorize_write(
    request: HttpRequest, note: Note, preview_as: UUID | None, noun: str = "note"
) -> None:
    """Raise HttpError if the caller may not edit/delete `note`."""
    if settings.SANDBOX_MODE:
        if note.is_seed:
            raise HttpError(403, "The demo content is read-only.")
        sk = request.session.session_key
        if not sk or note.session_key != sk:
            raise HttpError(403, "You can only change content you created in this session.")
    else:
        if preview_as is None or note.author_id != preview_as:
            raise HttpError(403, f"You can only edit your own {noun}s.")


def enforce_create_limits(request: HttpRequest, *, is_append: bool) -> tuple[str, str]:
    """Enforce sandbox creation caps and return (session_key, client_ip) to stamp on
    the new row. Raises HttpError(429) when a cap is hit. Caller guards on SANDBOX_MODE."""
    session_key = ensure_session(request)
    ip = client_ip(request)
    if Note.objects.filter(is_seed=False).count() >= MAX_EPHEMERAL_ROWS:
        raise HttpError(
            429,
            "The sandbox is full right now — content is pruned after 7 days. Try again later.",
        )
    # Soft caps: count-then-create isn't atomic, so a small overshoot under concurrency is
    # acceptable for a demo.
    hour_ago = timezone.now() - timedelta(hours=1)
    if ip and (
        Note.objects.filter(is_seed=False, created_ip=ip, created_at__gte=hour_ago).count()
        >= MAX_CREATES_PER_IP_PER_HOUR
    ):
        raise HttpError(429, "Too many additions from your network this hour — please slow down.")
    session_qs = Note.objects.filter(is_seed=False, session_key=session_key)
    if is_append:
        if session_qs.filter(parent__isnull=False).count() >= MAX_APPENDS_PER_SESSION:
            raise HttpError(429, "You've reached this session's append limit for the sandbox.")
    elif session_qs.filter(parent__isnull=True).count() >= MAX_NOTES_PER_SESSION:
        raise HttpError(429, "You've reached this session's note limit for the sandbox.")
    return session_key, ip
