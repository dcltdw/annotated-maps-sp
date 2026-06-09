import pytest
from django.contrib.gis.geos import Point
from django.test import Client

from core.models import Tenant, User
from maps.models import Map, Note, Section


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
