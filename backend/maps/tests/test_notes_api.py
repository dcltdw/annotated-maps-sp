import json

import pytest
from django.contrib.gis.geos import Point
from django.test import Client

from core.models import Group, Tenant, User
from maps.models import Map, Note, Section
from maps.visibility import section_label


@pytest.fixture
def boston(db):
    t = Tenant.objects.create(name="Boston", slug="boston")
    owner = User.objects.create(display_name="Owner")
    m = Map.objects.create(tenant=t, name="Boston", center=Point(-71.06, 42.36))
    note = Note.objects.create(
        tenant=t, map=m, author=owner, title="Castle Island", point=Point(-71.01, 42.33)
    )
    Section.objects.create(
        note=note, order=0, content="public bit", rule_type=Section.RuleType.PUBLIC
    )
    Section.objects.create(note=note, order=1, content="secret", rule_type=Section.RuleType.PRIVATE)
    return {"map": m, "owner": owner}


def test_guest_sees_only_public_section(boston):
    resp = Client().get(f"/api/v1/maps/{boston['map'].id}/notes")
    assert resp.status_code == 200
    notes = resp.json()
    assert len(notes) == 1
    sections = notes[0]["sections"]
    assert [s["visibility"] for s in sections] == ["visible"]
    assert sections[0]["content"] == "public bit"  # private section omitted (hidden)


def test_owner_preview_sees_all_sections(boston):
    resp = Client().get(f"/api/v1/maps/{boston['map'].id}/notes?preview_as={boston['owner'].id}")
    sections = resp.json()[0]["sections"]
    assert [s["visibility"] for s in sections] == ["visible", "visible"]
    assert sections[1]["content"] == "secret"


def test_guest_cannot_see_fully_hidden_note(boston):
    # A note whose sections are all hidden to the viewer must NOT appear at all
    # (no title / coordinate leak).
    secret = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        title="SECRET",
        point=Point(-71.0, 42.0),
    )
    Section.objects.create(note=secret, order=0, content="hush", rule_type=Section.RuleType.PRIVATE)
    titles = {n["title"] for n in Client().get(f"/api/v1/maps/{boston['map'].id}/notes").json()}
    assert "SECRET" not in titles  # fully-private note omitted for the guest
    assert "Castle Island" in titles  # the note with a public section still shows


def test_contributor_creates_a_point_note(boston):
    payload = {
        "title": "My spot",
        "lng": -71.05,
        "lat": 42.35,
        "sections": [{"order": 0, "content": "hi", "rule_type": "public"}],
    }
    resp = Client().post(
        f"/api/v1/maps/{boston['map'].id}/notes?preview_as={boston['owner'].id}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 201
    new_id = resp.json()["id"]
    assert Note.objects.filter(id=new_id, author=boston["owner"]).exists()


def test_guest_cannot_create(boston):
    resp = Client().post(
        f"/api/v1/maps/{boston['map'].id}/notes",
        data=json.dumps({"title": "x", "lng": -71.0, "lat": 42.0, "sections": []}),
        content_type="application/json",
    )
    assert resp.status_code == 403


def test_author_can_soft_delete_own_note(boston):
    note = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        point=Point(-71.0, 42.0),
    )
    resp = Client().delete(f"/api/v1/notes/{note.id}?preview_as={boston['owner'].id}")
    assert resp.status_code == 204
    assert Note.objects.filter(id=note.id).count() == 0  # hidden by default manager
    assert Note.all_objects.filter(id=note.id).count() == 1  # soft-deleted, still present


def test_non_author_cannot_delete(boston):
    other = User.objects.create(display_name="Someone else")
    note = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        point=Point(-71.0, 42.0),
    )
    resp = Client().delete(f"/api/v1/notes/{note.id}?preview_as={other.id}")
    assert resp.status_code == 403
    assert Note.objects.filter(id=note.id).count() == 1  # not deleted


def test_malformed_section_fails_closed_not_500(boston):
    # A section written with a bad rule_type (e.g. via a future bug or direct DB write)
    # must NOT 500 the list — it fails closed (owner-only → hidden for the guest).
    note = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        title="ok",
        point=Point(-71.0, 42.0),
    )
    Section.objects.create(
        note=note, order=0, content="public ok", rule_type=Section.RuleType.PUBLIC
    )
    Section.objects.create(
        note=note,
        order=1,
        content="broken",
        rule_type="bogus",  # invalid, direct write
    )
    resp = Client().get(f"/api/v1/maps/{boston['map'].id}/notes")
    assert resp.status_code == 200  # no 500
    shown = next(n for n in resp.json() if n["id"] == str(note.id))
    # broken section hidden (fails closed), not leaked
    assert all(s["content"] != "broken" for s in shown["sections"])


def test_create_rejects_invalid_rule_type(boston):
    payload = {
        "title": "x",
        "lng": -71.0,
        "lat": 42.0,
        "sections": [{"order": 0, "content": "c", "rule_type": "bogus"}],
    }
    resp = Client().post(
        f"/api/v1/maps/{boston['map'].id}/notes?preview_as={boston['owner'].id}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 422


def test_sections_carry_type_and_friendly_label(boston):
    resp = Client().get(f"/api/v1/maps/{boston['map'].id}/notes?preview_as={boston['owner'].id}")
    assert resp.status_code == 200
    sections = resp.json()[0]["sections"]
    by_type = {s["rule_type"]: s for s in sections}
    assert by_type["public"]["rule_label"] == "Public"
    assert by_type["private"]["rule_label"] == "Private"


def test_section_label_attribute_gate_humanizes_attribute_and_threshold():
    section = Section(
        rule_type=Section.RuleType.ATTRIBUTE_GATE,
        rule_params={"attribute": "reputation", "threshold": 50},
    )
    assert section_label(section) == "Reputation ≥ 50"


def test_section_label_audience_resolves_group_names(db):
    t = Tenant.objects.create(name="T", slug="t")
    g = Group.objects.create(tenant=t, name="Running club")
    section = Section(rule_type=Section.RuleType.AUDIENCE, rule_params={"group_ids": [str(g.id)]})
    assert section_label(section) == "Running club"


def test_section_label_audience_without_groups_says_friends():
    section = Section(rule_type=Section.RuleType.AUDIENCE, rule_params={})
    assert section_label(section) == "Friends"


def test_section_label_malformed_params_falls_back_to_restricted():
    # rule_params is not a mapping → params.get raises AttributeError → fail-soft label.
    section = Section(rule_type=Section.RuleType.ATTRIBUTE_GATE, rule_params="bad")
    assert section_label(section) == "Restricted"
