import json

from django.test import Client

from core.models import AuditEvent
from maps.models import Note


def _ephemeral(
    world, author, title="v", session="full-session-key-123", ip="203.0.113.5", parent=None
):
    return Note.objects.create(
        tenant=world["tenant"],
        map=world["map"],
        author=author,
        title=title,
        is_seed=False,
        session_key=session,
        created_ip=ip,
        parent=parent,
    )


def test_mod_recent_requires_token(world, settings):
    settings.MOD_TOKEN = "secret"
    assert Client().get("/api/v1/mod/recent").status_code == 401
    assert Client().get("/api/v1/mod/recent", HTTP_X_MOD_TOKEN="wrong").status_code == 401


def test_mod_recent_lists_ephemeral_not_seed(world, settings):
    settings.MOD_TOKEN = "secret"
    _ephemeral(world, world["alice"], title="visible one")
    r = Client().get("/api/v1/mod/recent", HTTP_X_MOD_TOKEN="secret")
    assert r.status_code == 200
    items = r.json()
    titles = [i["title"] for i in items]
    assert "visible one" in titles
    assert "Seed" not in titles  # the seed note is never listed
    item = next(i for i in items if i["title"] == "visible one")
    assert item["kind"] == "note"
    assert item["session_key"] == "full-session-key-123"  # FULL key (UI truncates it)
    assert item["created_ip"] == "203.0.113.5"
    assert item["author_name"] == "Alice"


def test_mod_recent_empty_token_setting_rejects_all(world, settings):
    settings.MOD_TOKEN = ""  # unset → inert
    assert Client().get("/api/v1/mod/recent", HTTP_X_MOD_TOKEN="").status_code == 401


def test_mod_delete_by_ids(world, settings):
    settings.MOD_TOKEN = "secret"
    n = _ephemeral(world, world["alice"], title="kill me")
    r = Client().post(
        "/api/v1/mod/delete",
        data=json.dumps({"ids": [str(n.id)]}),
        content_type="application/json",
        HTTP_X_MOD_TOKEN="secret",
    )
    assert r.status_code == 200 and r.json()["deleted"] == 1
    assert not Note.all_objects.filter(id=n.id).exists()


def test_mod_delete_by_session_then_ip(world, settings):
    settings.MOD_TOKEN = "secret"
    _ephemeral(world, world["alice"], session="abuser", ip="9.9.9.9")
    _ephemeral(world, world["bob"], session="abuser", ip="9.9.9.9")
    r = Client().post(
        "/api/v1/mod/delete",
        data=json.dumps({"session_key": "abuser"}),
        content_type="application/json",
        HTTP_X_MOD_TOKEN="secret",
    )
    assert r.json()["deleted"] == 2


def test_mod_delete_never_touches_seed(world, settings):
    settings.MOD_TOKEN = "secret"
    seed_id = str(world["seed"].id)
    r = Client().post(
        "/api/v1/mod/delete",
        data=json.dumps({"ids": [seed_id]}),
        content_type="application/json",
        HTTP_X_MOD_TOKEN="secret",
    )
    assert r.json()["deleted"] == 0
    assert Note.all_objects.filter(id=seed_id).exists()  # seed survives


def test_mod_delete_requires_token_and_exactly_one_criterion(world, settings):
    settings.MOD_TOKEN = "secret"
    # No token, but valid single-criterion body → should reach token check → 401
    assert (
        Client()
        .post(
            "/api/v1/mod/delete",
            data=json.dumps({"ids": []}),
            content_type="application/json",
        )
        .status_code
        == 401
    )
    # Token present, but two criteria → validator rejects → 422
    r = Client().post(
        "/api/v1/mod/delete",
        data=json.dumps({"session_key": "a", "created_ip": "1.1.1.1"}),
        content_type="application/json",
        HTTP_X_MOD_TOKEN="secret",
    )
    assert r.status_code == 422


def test_mod_delete_writes_audit_event(world, settings):
    settings.MOD_TOKEN = "secret"
    n = _ephemeral(world, world["alice"])
    Client().post(
        "/api/v1/mod/delete",
        data=json.dumps({"ids": [str(n.id)]}),
        content_type="application/json",
        HTTP_X_MOD_TOKEN="secret",
    )
    ev = AuditEvent.objects.filter(action="mod.delete").latest("created_at")
    assert ev.metadata["deleted"] == 1
