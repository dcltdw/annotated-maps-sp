"""Sandbox-mode behaviour for the public demo deploy. Everything here is gated by
settings.SANDBOX_MODE (default False → local dev + tests behave like a normal app)."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone
from ninja.errors import HttpError

from core.auth import Identity
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
    session_key = request.session.session_key
    assert session_key is not None  # create() above guarantees a key
    return session_key


def is_editable(request: HttpRequest, note: Note, identity: Identity) -> bool:
    """Whether the caller may edit/delete `note` (drives the read API's `editable`)."""
    if identity.user_id is None:
        return False
    if identity.is_authenticated:
        if settings.SANDBOX_MODE and note.is_seed:
            return False
        return note.author_id == identity.user_id
    # anonymous + sandbox (identity.user_id is only non-None here under SANDBOX_MODE)
    if note.is_seed:
        return False
    sk = request.session.session_key
    return bool(sk) and note.session_key == sk


def authorize_write(
    request: HttpRequest, note: Note, identity: Identity, noun: str = "note"
) -> None:
    """Raise HttpError if the caller may not edit/delete `note`."""
    if identity.user_id is None:
        raise HttpError(403, f"You can only edit your own {noun}s.")  # guest
    if identity.is_authenticated:
        if settings.SANDBOX_MODE and note.is_seed:
            raise HttpError(403, "The demo content is read-only.")
        if note.author_id != identity.user_id:
            raise HttpError(403, f"You can only edit your own {noun}s.")
        return
    # anonymous + sandbox
    if note.is_seed:
        raise HttpError(403, "The demo content is read-only.")
    sk = request.session.session_key
    if not sk or note.session_key != sk:
        raise HttpError(403, "You can only change content you created in this session.")


def enforce_create_limits(
    request: HttpRequest, *, is_append: bool, identity: Identity
) -> tuple[str, str | None]:
    """Enforce sandbox creation caps and return (session_key, client_ip) to stamp on the
    new row. Raises HttpError(429) when a cap is hit. Caller guards on SANDBOX_MODE.

    The global-rows and per-IP-hourly caps protect the deploy and apply to EVERY creator
    (authenticated or anonymous). The per-session caps are anonymous-only: authenticated
    creators are bucketed by author id, not session."""
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
    if identity.is_authenticated:
        # Authenticated creators are bucketed by author id, not session, so the per-session
        # caps below don't apply. We don't yet impose a per-user create quota — the IP +
        # global caps above bound abuse even with the public demo-persona login. To add a
        # per-user cap later, count
        #   Note.objects.filter(author_id=identity.user_id, is_seed=False, ...).count()
        # here, mirroring the per-session branch below, and raise 429 past the threshold.
        return "", (ip or None)
    session_key = ensure_session(request)
    session_qs = Note.objects.filter(is_seed=False, session_key=session_key)
    if is_append:
        if session_qs.filter(parent__isnull=False).count() >= MAX_APPENDS_PER_SESSION:
            raise HttpError(429, "You've reached this session's append limit for the sandbox.")
    elif session_qs.filter(parent__isnull=True).count() >= MAX_NOTES_PER_SESSION:
        raise HttpError(429, "You've reached this session's note limit for the sandbox.")
    return session_key, (ip or None)
