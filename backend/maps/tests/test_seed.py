import pytest

from maps.models import Map, Note
from maps.seed import build_boston_demo


@pytest.mark.django_db
def test_seed_builds_the_castle_island_demo():
    data = build_boston_demo()
    assert Map.objects.filter(name__icontains="Boston").exists()
    note = Note.objects.get(title__icontains="Castle Island")
    types = set(note.sections.values_list("rule_type", flat=True))
    assert {"public", "audience", "attribute_gate", "private"} <= types
    assert data["owner"].id == note.author_id


@pytest.mark.django_db
def test_seed_includes_an_area_and_a_route(db):
    from maps.seed import build_boston_demo

    data = build_boston_demo()
    assert data["area_note"].area is not None and data["area_note"].is_seed
    assert data["route_note"].path is not None and data["route_note"].is_seed


def test_seed_demo_refresh_rebuilds_seed_only(db):
    from django.contrib.gis.geos import Point
    from django.core.management import call_command

    data = build_boston_demo()
    seed_count = Note.objects.filter(is_seed=True).count()
    assert seed_count > 0
    # A user-created (non-seed) note must survive a refresh untouched.
    user_note = Note.objects.create(
        tenant=data["tenant"],
        map=data["map"],
        author=data["friend"],
        title="a visitor's pin",
        point=Point(-71.06, 42.35),
        is_seed=False,
    )

    call_command("seed_demo", "--refresh")

    # Seed content is rebuilt, not duplicated; user content is left alone.
    assert Note.objects.filter(is_seed=True).count() == seed_count
    assert Note.objects.filter(id=user_note.id).exists()


def test_seed_china_pearl_is_friends_only(db):
    data = build_boston_demo()
    pin = data["china_pearl"]
    assert pin.point is not None and pin.is_seed
    # The pin's only top-level section is friend-audience, so list_notes (which hides a
    # note when no section is visible to the viewer) shows it to the friend alone.
    sections = list(pin.sections.all())
    assert len(sections) == 1
    assert sections[0].rule_type == "audience"
    assert str(data["friend"].id) in sections[0].rule_params["user_ids"]
    # The friend's own take is a friend-authored append on the same pin.
    appends = list(pin.appends.all())
    assert len(appends) == 1
    assert appends[0].author_id == data["friend"].id
    assert "shumai" in (appends[0].sections.first().content or "").lower()


def test_seed_personas_can_log_in(db):
    from django.contrib.auth.hashers import check_password

    from maps.seed import DEMO_PASSWORD, build_boston_demo

    data = build_boston_demo()
    friend = data["friend"]
    assert friend.email == "friend@demo.example"
    assert check_password(DEMO_PASSWORD, friend.password)  # the seeded login works
    assert data["owner"].email == "owner@demo.example"
    assert data["runner"].email == "runner@demo.example"
    assert data["local"].email == "local@demo.example"
