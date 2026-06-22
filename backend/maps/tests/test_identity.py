import json

import pytest
from django.contrib.gis.geos import Point
from django.test import Client

from core.models import Membership, Tenant, User
from maps.models import Map, Note, Section
from maps.tests.conftest import client_as


@pytest.fixture
def scene(db):
    t = Tenant.objects.create(name="Boston", slug="boston")
    real = User.objects.create(display_name="Real")
    persona = User.objects.create(display_name="Persona")
    Membership.objects.create(tenant=t, user=real, role=Membership.Role.CONTRIBUTOR)
    Membership.objects.create(tenant=t, user=persona, role=Membership.Role.VIEWER)
    m = Map.objects.create(tenant=t, name="Boston", center=Point(-71.06, 42.36))
    note = Note.objects.create(tenant=t, map=m, author=real, title="N", point=Point(-71.0, 42.3))
    Section.objects.create(note=note, order=0, content="hi", rule_type=Section.RuleType.PUBLIC)
    return {"map": m, "note": note, "real": real, "persona": persona}


def _edit_body():
    return {
        "title": "Edited",
        "lng": -71.0,
        "lat": 42.3,
        "version": 1,
        "sections": [
            {
                "order": 0,
                "content": "x",
                "rule_type": "public",
                "rule_params": {},
                "teaser": False,
                "teaser_text": "",
            }
        ],
    }


def test_authenticated_user_wins_over_a_bogus_preview_as(scene):
    # The author edits their own note while passing someone else's preview_as — still allowed,
    # because the authenticated identity wins and preview_as is ignored.
    url = f"/api/v1/notes/{scene['note'].id}?preview_as={scene['persona'].id}"
    resp = client_as(scene["real"]).put(
        url, data=json.dumps(_edit_body()), content_type="application/json"
    )
    assert resp.status_code == 200


def test_preview_as_is_ignored_for_writes_when_authenticated(scene):
    # A different authenticated user cannot edit the author's note even if preview_as
    # names the author.
    url = f"/api/v1/notes/{scene['note'].id}?preview_as={scene['real'].id}"
    resp = client_as(scene["persona"]).put(
        url, data=json.dumps(_edit_body()), content_type="application/json"
    )
    assert resp.status_code == 403  # preview_as can't impersonate while authenticated


def test_preview_as_is_guest_outside_sandbox(scene, settings):
    # SANDBOX_MODE False (default): an anonymous caller with preview_as is a guest → cannot write.
    settings.SANDBOX_MODE = False
    url = f"/api/v1/notes/{scene['note'].id}?preview_as={scene['real'].id}"
    resp = Client().put(url, data=json.dumps(_edit_body()), content_type="application/json")
    assert resp.status_code == 403


def test_preview_as_honored_when_anonymous_and_sandbox(scene, settings):
    # SANDBOX_MODE True + anonymous + preview_as=author → the read sees the author's visibility.
    settings.SANDBOX_MODE = True
    url = f"/api/v1/maps/{scene['map'].id}/notes?preview_as={scene['real'].id}"
    resp = Client().get(url)
    assert resp.status_code == 200 and len(resp.json()) == 1
