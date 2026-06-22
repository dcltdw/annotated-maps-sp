from datetime import timedelta

from django.test import RequestFactory
from django.utils import timezone


def _req(token: str | None):
    factory = RequestFactory()
    if token:
        return factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}")
    return factory.get("/")


def test_create_session_returns_raw_token_and_stores_only_its_hash(db):
    from core.auth import create_session, hash_token
    from core.models import AuthSession, User

    u = User.objects.create(display_name="X")
    token = create_session(u, _req(None))
    assert token and len(token) > 20
    s = AuthSession.objects.get(user=u)
    assert s.token_hash == hash_token(token)  # only the hash is stored
    assert token not in s.token_hash  # raw token is NOT in the DB


def test_authed_user_resolves_a_live_session(db):
    from core.auth import authed_user, create_session
    from core.models import User

    u = User.objects.create(display_name="X")
    token = create_session(u, _req(None))
    assert authed_user(_req(token)) == u


def test_authed_user_rejects_missing_garbage_and_expired_tokens(db):
    from core.auth import authed_user, create_session
    from core.models import AuthSession, User

    u = User.objects.create(display_name="X")
    assert authed_user(_req(None)) is None
    assert authed_user(_req("not-a-real-token")) is None
    token = create_session(u, _req(None))
    AuthSession.objects.filter(user=u).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert authed_user(_req(token)) is None  # expired


def test_resolve_identity_authenticated_bearer_always_wins(db, settings):
    from core.auth import create_session, resolve_identity
    from core.models import User

    settings.SANDBOX_MODE = True
    real = User.objects.create(display_name="Real")
    persona = User.objects.create(display_name="Persona")
    token = create_session(real, _req(None))
    # Even with a preview_as persona AND sandbox on, the bearer user wins.
    ident = resolve_identity(_req(token), persona.id)
    assert ident.user_id == real.id and ident.is_authenticated is True


def test_resolve_identity_preview_as_only_when_anonymous_and_sandbox(db, settings):
    from core.auth import resolve_identity
    from core.models import User

    persona = User.objects.create(display_name="Persona")
    settings.SANDBOX_MODE = True
    ident = resolve_identity(_req(None), persona.id)
    assert ident.user_id == persona.id and ident.is_authenticated is False


def test_resolve_identity_ignores_preview_as_outside_sandbox(db, settings):
    from core.auth import resolve_identity
    from core.models import User

    persona = User.objects.create(display_name="Persona")
    settings.SANDBOX_MODE = False
    ident = resolve_identity(_req(None), persona.id)
    assert ident.user_id is None and ident.is_authenticated is False


def test_resolve_identity_guest_when_no_identity(db, settings):
    from core.auth import resolve_identity

    settings.SANDBOX_MODE = True
    ident = resolve_identity(_req(None), None)
    assert ident.user_id is None and ident.is_authenticated is False
