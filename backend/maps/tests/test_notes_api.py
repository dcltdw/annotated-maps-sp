import json
import warnings

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
        tenant=t, map=m, author=owner, title="Beacon Hill", point=Point(-71.01, 42.33)
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
    assert "Beacon Hill" in titles  # the note with a public section still shows


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
        data=json.dumps(
            {
                "title": "x",
                "lng": -71.0,
                "lat": 42.0,
                "sections": [{"content": "c", "rule_type": "public"}],
            }
        ),
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


def test_teaser_section_returns_custom_teaser_text_and_note_returns_author(boston):
    note = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        title="Hook note",
        point=Point(-71.02, 42.34),
    )
    Section.objects.create(note=note, order=0, content="public", rule_type=Section.RuleType.PUBLIC)
    Section.objects.create(
        note=note,
        order=1,
        content="secret",
        rule_type=Section.RuleType.PRIVATE,
        teaser=True,
        teaser_text="ask me nicely",
    )
    notes = Client().get(f"/api/v1/maps/{boston['map'].id}/notes").json()
    data = next(n for n in notes if n["title"] == "Hook note")
    assert data["author_id"] == str(boston["owner"].id)
    teaser = next(s for s in data["sections"] if s["visibility"] == "teaser")
    assert teaser["teaser_text"] == "ask me nicely"
    public = next(s for s in data["sections"] if s["visibility"] == "visible")
    assert public["teaser_text"] is None  # only locked sections carry the hook


def test_locked_section_with_empty_teaser_text_returns_null(boston):
    note = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        title="Empty hook",
        point=Point(-71.0, 42.0),
    )
    Section.objects.create(note=note, order=0, content="public", rule_type=Section.RuleType.PUBLIC)
    Section.objects.create(
        note=note, order=1, content="secret", rule_type=Section.RuleType.PRIVATE, teaser=True
    )  # teaser=True, teaser_text defaults to ""
    notes = Client().get(f"/api/v1/maps/{boston['map'].id}/notes").json()
    data = next(n for n in notes if n["title"] == "Empty hook")
    teaser = next(s for s in data["sections"] if s["visibility"] == "teaser")
    assert teaser["teaser_text"] is None  # empty hook collapses to null, not ""


def _post(boston, payload):
    return Client().post(
        f"/api/v1/maps/{boston['map'].id}/notes?preview_as={boston['owner'].id}",
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_create_rejects_empty_title(boston):
    assert (
        _post(
            boston,
            {
                "title": "  ",
                "lng": -71.0,
                "lat": 42.0,
                "sections": [{"content": "c", "rule_type": "public"}],
            },
        ).status_code
        == 422
    )


def test_create_rejects_zero_sections(boston):
    resp = _post(boston, {"title": "x", "lng": -71.0, "lat": 42.0, "sections": []})
    assert resp.status_code == 422


def test_create_rejects_empty_section_content(boston):
    assert (
        _post(
            boston,
            {
                "title": "x",
                "lng": -71.0,
                "lat": 42.0,
                "sections": [{"content": " ", "rule_type": "public"}],
            },
        ).status_code
        == 422
    )


def test_create_rejects_audience_without_target(boston):
    resp = _post(
        boston,
        {
            "title": "x",
            "lng": -71.0,
            "lat": 42.0,
            "sections": [{"content": "c", "rule_type": "audience", "rule_params": {}}],
        },
    )
    assert resp.status_code == 422


def test_create_stores_teaser_text(boston):
    resp = _post(
        boston,
        {
            "title": "x",
            "lng": -71.0,
            "lat": 42.0,
            "sections": [
                {"content": "c", "rule_type": "private", "teaser": True, "teaser_text": "psst"}
            ],
        },
    )
    assert resp.status_code == 201
    note = Note.objects.get(id=resp.json()["id"])
    section = note.sections.first()
    assert section is not None
    assert section.teaser_text == "psst"


def _note_with_sections(boston):
    note = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        title="Editable",
        point=Point(-71.03, 42.36),
    )
    Section.objects.create(note=note, order=0, content="pub", rule_type=Section.RuleType.PUBLIC)
    Section.objects.create(
        note=note,
        order=1,
        content="gate",
        rule_type=Section.RuleType.ATTRIBUTE_GATE,
        rule_params={"attribute": "reputation", "threshold": 50},
        teaser=True,
        teaser_text="earn it",
    )
    return note


def test_author_gets_raw_note_for_edit(boston):
    note = _note_with_sections(boston)
    body = Client().get(f"/api/v1/notes/{note.id}/edit?preview_as={boston['owner'].id}").json()
    assert body["title"] == "Editable"
    assert body["version"] == note.version
    gate = body["sections"][1]
    assert gate["rule_params"]["threshold"] == 50
    assert gate["teaser"] is True and gate["teaser_text"] == "earn it"


def test_non_author_cannot_get_edit(boston):
    note = _note_with_sections(boston)
    other = User.objects.create(display_name="Nope")
    assert Client().get(f"/api/v1/notes/{note.id}/edit?preview_as={other.id}").status_code == 403
    assert Client().get(f"/api/v1/notes/{note.id}/edit").status_code == 403  # guest


def _put(note_id, payload, who):
    return Client().put(
        f"/api/v1/notes/{note_id}?preview_as={who}",
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_author_edits_own_note(boston):
    note = _note_with_sections(boston)
    payload = {
        "title": "Edited",
        "lng": -71.04,
        "lat": 42.37,
        "version": note.version,
        "sections": [{"order": 0, "content": "only one now", "rule_type": "public"}],
    }
    resp = _put(note.id, payload, boston["owner"].id)
    assert resp.status_code == 200
    assert resp.json()["id"] == str(note.id)
    assert resp.json()["version"] == note.version + 1
    note.refresh_from_db()
    assert note.title == "Edited"
    assert note.sections.count() == 1  # replaced wholesale


def test_edit_rejects_invalid_body(boston):
    # NoteUpdateIn inherits NoteIn's validators — a malformed edit body 422s before the handler.
    note = _note_with_sections(boston)
    payload = {
        "title": "  ",
        "lng": -71.0,
        "lat": 42.0,
        "version": note.version,
        "sections": [{"order": 0, "content": "c", "rule_type": "public"}],
    }
    assert _put(note.id, payload, boston["owner"].id).status_code == 422


def test_edit_version_conflict_returns_409(boston):
    note = _note_with_sections(boston)
    stale = note.version
    note.title = "bumped"
    note.save()  # version advances under us
    payload = {
        "title": "x",
        "lng": -71.0,
        "lat": 42.0,
        "version": stale,
        "sections": [{"order": 0, "content": "c", "rule_type": "public"}],
    }
    assert _put(note.id, payload, boston["owner"].id).status_code == 409


def test_two_edits_with_the_same_starting_version_second_conflicts(boston):
    note = _note_with_sections(boston)
    v0 = note.version
    body = {
        "title": "first",
        "lng": -71.0,
        "lat": 42.0,
        "version": v0,
        "sections": [{"order": 0, "content": "a", "rule_type": "public"}],
    }
    r1 = _put(note.id, body, boston["owner"].id)
    assert r1.status_code == 200 and r1.json()["version"] == v0 + 1
    body["title"] = "second"
    r2 = _put(note.id, body, boston["owner"].id)
    assert r2.status_code == 409
    note.refresh_from_db()
    assert note.title == "first"  # the conflicting second edit did not apply


def test_non_author_cannot_edit(boston):
    note = _note_with_sections(boston)
    other = User.objects.create(display_name="Nope")
    payload = {
        "title": "x",
        "lng": -71.0,
        "lat": 42.0,
        "version": note.version,
        "sections": [{"order": 0, "content": "c", "rule_type": "public"}],
    }
    assert _put(note.id, payload, other.id).status_code == 403


def test_guest_cannot_edit(boston):
    note = _note_with_sections(boston)
    resp = Client().put(
        f"/api/v1/notes/{note.id}",
        data=json.dumps(
            {
                "title": "x",
                "lng": -71.0,
                "lat": 42.0,
                "version": note.version,
                "sections": [{"order": 0, "content": "c", "rule_type": "public"}],
            }
        ),
        content_type="application/json",
    )
    assert resp.status_code == 403


def test_appends_nest_under_parent_and_filter_independently(boston):
    parent = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        title="Castle Island",
        point=Point(-71.01, 42.33),
    )
    Section.objects.create(note=parent, order=0, content="loop", rule_type=Section.RuleType.PUBLIC)
    friend = User.objects.create(display_name="A Friend")
    ap = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=friend,
        parent=parent,
        title="Tip",
    )
    Section.objects.create(
        note=ap, order=0, content="sunset photos", rule_type=Section.RuleType.PUBLIC
    )
    Section.objects.create(
        note=ap, order=1, content="my private note", rule_type=Section.RuleType.PRIVATE
    )

    data = Client().get(f"/api/v1/maps/{boston['map'].id}/notes").json()
    titles = [n["title"] for n in data]
    assert "Tip" not in titles  # appends are NOT top-level
    castle = next(n for n in data if n["title"] == "Castle Island")
    assert len(castle["appends"]) == 1
    a = castle["appends"][0]
    assert a["author_name"] == "A Friend" and a["title"] == "Tip"
    assert [s["content"] for s in a["sections"]] == ["sunset photos"]  # private hidden from guest

    as_friend = Client().get(f"/api/v1/maps/{boston['map'].id}/notes?preview_as={friend.id}").json()
    a2 = next(n for n in as_friend if n["title"] == "Castle Island")["appends"][0]
    assert "my private note" in [s["content"] for s in a2["sections"]]

    as_owner = (
        Client()
        .get(f"/api/v1/maps/{boston['map'].id}/notes?preview_as={boston['owner'].id}")
        .json()
    )
    a3 = next(n for n in as_owner if n["title"] == "Castle Island")["appends"][0]
    assert "my private note" not in [s["content"] for s in a3["sections"]]


def _append(parent_id, payload, who):
    return Client().post(
        f"/api/v1/notes/{parent_id}/appends?preview_as={who}",
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_contributor_appends_to_anothers_note(boston):
    parent = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        title="Castle",
        point=Point(-71.0, 42.0),
    )
    friend = User.objects.create(display_name="A Friend")
    resp = _append(
        parent.id,
        {"title": "Tip", "sections": [{"content": "sunset", "rule_type": "public"}]},
        friend.id,
    )
    assert resp.status_code == 201
    ap = Note.objects.get(id=resp.json()["id"])
    assert ap.parent_id == parent.id and ap.author_id == friend.id and ap.point is None
    assert ap.map_id == parent.map_id


def test_append_allows_empty_title(boston):
    parent = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        point=Point(-71.0, 42.0),
    )
    resp = _append(
        parent.id,
        {"sections": [{"content": "c", "rule_type": "public"}]},
        boston["owner"].id,
    )
    assert resp.status_code == 201
    assert Note.objects.get(id=resp.json()["id"]).title == ""


def test_guest_cannot_append(boston):
    parent = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        point=Point(-71.0, 42.0),
    )
    resp = Client().post(
        f"/api/v1/notes/{parent.id}/appends",
        data=json.dumps({"sections": [{"content": "c", "rule_type": "public"}]}),
        content_type="application/json",
    )
    assert resp.status_code == 403


def test_cannot_append_to_an_append(boston):
    parent = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        point=Point(-71.0, 42.0),
    )
    child = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        parent=parent,
    )
    resp = _append(
        child.id,
        {"sections": [{"content": "c", "rule_type": "public"}]},
        boston["owner"].id,
    )
    assert resp.status_code == 400


def test_append_rejects_zero_sections(boston):
    parent = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        point=Point(-71.0, 42.0),
    )
    assert _append(parent.id, {"sections": []}, boston["owner"].id).status_code == 422


def _make_append(boston, author):
    parent = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        point=Point(-71.0, 42.0),
    )
    ap = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=author,
        parent=parent,
        title="T",
    )
    Section.objects.create(note=ap, order=0, content="orig", rule_type=Section.RuleType.PUBLIC)
    return ap


def test_author_edits_own_append(boston):
    friend = User.objects.create(display_name="A Friend")
    ap = _make_append(boston, friend)
    payload = {
        "title": "T2",
        "version": ap.version,
        "sections": [{"order": 0, "content": "new", "rule_type": "public"}],
    }
    resp = Client().put(
        f"/api/v1/appends/{ap.id}?preview_as={friend.id}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200 and resp.json()["version"] == ap.version + 1
    ap.refresh_from_db()
    assert ap.title == "T2" and ap.sections.first().content == "new"


def test_non_author_cannot_edit_append(boston):
    friend = User.objects.create(display_name="A Friend")
    ap = _make_append(boston, friend)
    payload = {
        "version": ap.version,
        "sections": [{"order": 0, "content": "x", "rule_type": "public"}],
    }
    assert (
        Client()
        .put(
            f"/api/v1/appends/{ap.id}?preview_as={boston['owner'].id}",
            data=json.dumps(payload),
            content_type="application/json",
        )
        .status_code
        == 403
    )


def test_append_edit_version_conflict_409(boston):
    friend = User.objects.create(display_name="A Friend")
    ap = _make_append(boston, friend)
    stale = ap.version
    ap.title = "bumped"
    ap.save()
    payload = {
        "version": stale,
        "sections": [{"order": 0, "content": "x", "rule_type": "public"}],
    }
    assert (
        Client()
        .put(
            f"/api/v1/appends/{ap.id}?preview_as={friend.id}",
            data=json.dumps(payload),
            content_type="application/json",
        )
        .status_code
        == 409
    )


def test_two_append_edits_with_the_same_starting_version_second_conflicts(boston):
    friend = User.objects.create(display_name="A Friend")
    ap = _make_append(boston, friend)
    v0 = ap.version
    payload = {
        "title": "first",
        "version": v0,
        "sections": [{"order": 0, "content": "a", "rule_type": "public"}],
    }
    r1 = Client().put(
        f"/api/v1/appends/{ap.id}?preview_as={friend.id}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert r1.status_code == 200 and r1.json()["version"] == v0 + 1
    payload["title"] = "second"
    r2 = Client().put(
        f"/api/v1/appends/{ap.id}?preview_as={friend.id}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert r2.status_code == 409
    ap.refresh_from_db()
    assert ap.title == "first"  # the conflicting second edit did not apply


def test_delete_and_edit_endpoints_work_on_an_append(boston):
    friend = User.objects.create(display_name="A Friend")
    ap = _make_append(boston, friend)
    edit = Client().get(f"/api/v1/notes/{ap.id}/edit?preview_as={friend.id}").json()
    assert edit["title"] == "T" and edit["lng"] is None  # append has no point
    assert Client().delete(f"/api/v1/notes/{ap.id}?preview_as={friend.id}").status_code == 204
    assert Note.objects.filter(id=ap.id).count() == 0  # soft-deleted


def test_guest_cannot_edit_append(boston):
    friend = User.objects.create(display_name="A Friend")
    ap = _make_append(boston, friend)
    payload = {
        "version": ap.version,
        "sections": [{"order": 0, "content": "x", "rule_type": "public"}],
    }
    resp = Client().put(
        f"/api/v1/appends/{ap.id}", data=json.dumps(payload), content_type="application/json"
    )
    assert resp.status_code == 403


def test_cannot_edit_a_top_level_note_via_the_append_endpoint(boston):
    # A top-level note must NOT be editable through /appends/{id} — that would bypass
    # the note write schema (e.g. its required title). The author gets 400, not a mutation.
    note = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        title="Top",
        point=Point(-71.0, 42.0),
    )
    payload = {
        "title": "",
        "version": note.version,
        "sections": [{"order": 0, "content": "x", "rule_type": "public"}],
    }
    resp = Client().put(
        f"/api/v1/appends/{note.id}?preview_as={boston['owner'].id}",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 400
    note.refresh_from_db()
    assert note.title == "Top"  # unchanged


def test_create_does_not_emit_the_tuple_return_deprecation(boston):
    payload = {
        "title": "x",
        "lng": -71.0,
        "lat": 42.0,
        "sections": [{"content": "c", "rule_type": "public"}],
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resp = Client().post(
            f"/api/v1/maps/{boston['map'].id}/notes?preview_as={boston['owner'].id}",
            data=json.dumps(payload),
            content_type="application/json",
        )
    assert resp.status_code == 201
    assert not any("Returning tuple" in str(w.message) for w in caught)


def test_list_returns_polygon_shape_for_area_notes(boston):
    from django.contrib.gis.geos import Polygon

    from maps.models import Note, Section

    n = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        title="park",
        area=Polygon(((-71.1, 42.3), (-71.1, 42.4), (-71.0, 42.4), (-71.1, 42.3))),
    )
    Section.objects.create(note=n, order=0, content="green", rule_type="public")
    r = Client().get(f"/api/v1/maps/{boston['map'].id}/notes")
    got = next(x for x in r.json() if x["title"] == "park")
    assert got["lng"] is None and got["lat"] is None
    assert got["shape"]["kind"] == "polygon"
    assert got["shape"]["coordinates"][0] == [-71.1, 42.3]  # [lng, lat] pairs


def test_list_returns_line_shape_for_path_notes(boston):
    from django.contrib.gis.geos import LineString

    from maps.models import Note, Section

    n = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        title="route",
        path=LineString((-71.1, 42.3), (-71.0, 42.35), (-70.9, 42.3)),
    )
    Section.objects.create(note=n, order=0, content="run", rule_type="public")
    r = Client().get(f"/api/v1/maps/{boston['map'].id}/notes")
    got = next(x for x in r.json() if x["title"] == "route")
    assert got["shape"]["kind"] == "line"
    assert len(got["shape"]["coordinates"]) == 3


def test_point_notes_have_null_shape(boston):
    r = Client().get(f"/api/v1/maps/{boston['map'].id}/notes")
    got = next(x for x in r.json() if x["title"] == "Beacon Hill")  # the fixture point note
    assert got["shape"] is None and got["lng"] is not None


def _post_note(boston, body):
    return Client().post(
        f"/api/v1/maps/{boston['map'].id}/notes?preview_as={boston['owner'].id}",
        data=json.dumps(body),
        content_type="application/json",
    )


def test_create_rejects_both_point_and_shape(boston):
    body = {
        "title": "x",
        "lng": -71.0,
        "lat": 42.0,
        "shape": {"kind": "polygon", "coordinates": [[-71, 42], [-71, 43], [-70, 43], [-71, 42]]},
        "sections": [{"order": 0, "content": "c", "rule_type": "public"}],
    }
    assert _post_note(boston, body).status_code == 422


def test_create_rejects_no_anchor(boston):
    body = {"title": "x", "sections": [{"order": 0, "content": "c", "rule_type": "public"}]}
    assert _post_note(boston, body).status_code == 422


def test_create_a_polygon_note(boston):
    body = {
        "title": "park",
        "shape": {"kind": "polygon", "coordinates": [[-71.1, 42.3], [-71.1, 42.4], [-71.0, 42.4]]},
        "sections": [{"order": 0, "content": "green", "rule_type": "public"}],
    }
    r = _post_note(boston, body)
    assert r.status_code == 201
    from maps.models import Note

    n = Note.objects.get(id=r.json()["id"])
    assert n.area is not None and n.point is None and n.path is None


def test_create_a_line_note(boston):
    body = {
        "title": "route",
        "shape": {"kind": "line", "coordinates": [[-71.1, 42.3], [-71.0, 42.35]]},
        "sections": [{"order": 0, "content": "run", "rule_type": "public"}],
    }
    r = _post_note(boston, body)
    assert r.status_code == 201
    from maps.models import Note

    n = Note.objects.get(id=r.json()["id"])
    assert n.path is not None and n.point is None and n.area is None


def test_create_rejects_self_intersecting_polygon(boston):
    body = {
        "title": "bad",
        "shape": {"kind": "polygon", "coordinates": [[0, 0], [1, 1], [1, 0], [0, 1]]},
        "sections": [{"order": 0, "content": "c", "rule_type": "public"}],
    }
    assert _post_note(boston, body).status_code == 422


def _put_note(boston, note_id, body):
    return Client().put(
        f"/api/v1/notes/{note_id}?preview_as={boston['owner'].id}",
        data=json.dumps(body),
        content_type="application/json",
    )


def test_edit_converts_point_note_to_polygon(boston):
    note = _note_with_sections(boston)  # an editable point note authored by owner
    body = {
        "title": note.title,
        "version": note.version,
        "shape": {"kind": "polygon", "coordinates": [[-71.1, 42.3], [-71.1, 42.4], [-71.0, 42.4]]},
        "sections": [{"order": 0, "content": "now an area", "rule_type": "public"}],
    }
    r = _put_note(boston, note.id, body)
    assert r.status_code == 200
    note.refresh_from_db()
    assert note.area is not None and note.point is None and note.path is None


def test_edit_converts_polygon_back_to_point(boston):
    from django.contrib.gis.geos import Polygon

    from maps.models import Note, Section

    n = Note.objects.create(
        tenant=boston["map"].tenant,
        map=boston["map"],
        author=boston["owner"],
        title="area",
        area=Polygon(((-71.1, 42.3), (-71.1, 42.4), (-71.0, 42.4), (-71.1, 42.3))),
    )
    Section.objects.create(note=n, order=0, content="x", rule_type="public")
    body = {
        "title": "now a pin",
        "version": n.version,
        "lng": -71.05,
        "lat": 42.35,
        "sections": [{"order": 0, "content": "pin", "rule_type": "public"}],
    }
    r = _put_note(boston, n.id, body)
    assert r.status_code == 200
    n.refresh_from_db()
    assert n.point is not None and n.area is None and n.path is None
