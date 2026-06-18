import json

from django.test import Client, RequestFactory

from maps.models import Note
from maps.sandbox import client_ip


def test_client_ip_uses_last_forwarded_for_hop():
    # Render appends the real client IP to the right; the leftmost hop is client-forgeable.
    req = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.7", REMOTE_ADDR="10.0.0.1"
    )
    assert client_ip(req) == "203.0.113.7"


def test_client_ip_ignores_a_forged_leftmost_hop():
    req = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="9.9.9.9", REMOTE_ADDR="10.0.0.1")
    # single hop → that hop is the one Render appended (the real client)
    assert client_ip(req) == "9.9.9.9"


def test_client_ip_falls_back_to_remote_addr():
    req = RequestFactory().get("/", REMOTE_ADDR="198.51.100.4")
    assert client_ip(req) == "198.51.100.4"


def _create_note(client, world, author, title="mine"):
    payload = {
        "title": title,
        "lng": -71.05,
        "lat": 42.35,
        "sections": [{"order": 0, "content": "c", "rule_type": "public"}],
    }
    r = client.post(
        f"/api/v1/maps/{world['map'].id}/notes?preview_as={author.id}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert r.status_code == 201, r.content
    return r.json()["id"]


def test_sandbox_seed_is_read_only(world, settings):
    settings.SANDBOX_MODE = True
    seed_id = world["seed"].id
    r = Client().delete(f"/api/v1/notes/{seed_id}?preview_as={world['alice'].id}")
    assert r.status_code == 403


def test_sandbox_session_owns_its_writes(world, settings):
    settings.SANDBOX_MODE = True
    owner = Client()  # one Client == one session (cookies persist across its requests)
    note_id = _create_note(owner, world, world["alice"])
    other = Client()
    assert (
        other.delete(f"/api/v1/notes/{note_id}?preview_as={world['alice'].id}").status_code == 403
    )
    assert (
        owner.delete(f"/api/v1/notes/{note_id}?preview_as={world['alice'].id}").status_code == 204
    )


def test_sandbox_per_session_note_cap(world, settings, monkeypatch):
    settings.SANDBOX_MODE = True
    import maps.sandbox as sb

    monkeypatch.setattr(sb, "MAX_NOTES_PER_SESSION", 2)  # keep the test fast
    c = Client()
    _create_note(c, world, world["alice"])
    _create_note(c, world, world["alice"])
    payload = {
        "title": "third",
        "lng": -71.05,
        "lat": 42.35,
        "sections": [{"order": 0, "content": "c", "rule_type": "public"}],
    }
    r = c.post(
        f"/api/v1/maps/{world['map'].id}/notes?preview_as={world['alice'].id}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert r.status_code == 429


def test_sandbox_stamps_session_and_ip_on_create(world, settings):
    settings.SANDBOX_MODE = True
    note_id = _create_note(Client(), world, world["alice"])
    n = Note.objects.get(id=note_id)
    assert n.is_seed is False and n.session_key != "" and n.created_ip is not None


def test_non_sandbox_create_is_uncapped_and_unstamped(world, settings):
    settings.SANDBOX_MODE = False
    note_id = _create_note(Client(), world, world["alice"])
    n = Note.objects.get(id=note_id)
    assert n.session_key == "" and n.created_ip is None
