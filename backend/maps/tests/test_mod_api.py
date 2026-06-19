from django.test import Client

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
