# backend/maps/tests/test_seed.py
import pytest
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.gis.geos import Point

from core.models import User
from maps.models import Map, Note
from maps.seed import DEMO_PASSWORD, build_boston_demo


@pytest.mark.django_db
def test_seed_builds_the_demo_map_and_cast():
    data = build_boston_demo()
    assert Map.objects.filter(name__icontains="Boston").exists()
    assert set(data["notes_by_slug"]) >= {
        "castle-island-loop",
        "boston-public-garden",
        "charles-river-loop",
        "china-pearl",
    }
    # Two groups with the spec'd memberships
    assert set(data["running_club"].members.all()) == {data["runner"], data["running_friend"]}
    assert set(data["dim_sum_crew"].members.all()) == {data["dimsum_friend"]}


@pytest.mark.django_db
def test_friend_tier_targets_both_friends():
    data = build_boston_demo()
    note = data["notes_by_slug"]["castle-island-loop"]
    aud = note.sections.filter(rule_type="audience", rule_params__has_key="user_ids").get()
    assert set(aud.rule_params["user_ids"]) == {
        str(data["running_friend"].id),
        str(data["dimsum_friend"].id),
    }


@pytest.mark.django_db
def test_showcase_invariant():
    """The demo tour opens this note by title — see the demo-tour spec.

    If this test fails you are editing the TOUR SHOWCASE: re-read
    docs/superpowers/specs/2026-07-04-demo-tour-design.md before proceeding.
    """
    from maps.seed_schema import SHOWCASE_TITLE

    build_boston_demo()
    note = Note.objects.get(title=SHOWCASE_TITLE, parent__isnull=True)
    assert note.path is not None  # it's the route, center-viewport
    types = set(note.sections.values_list("rule_type", flat=True))
    assert {"public", "audience", "attribute_gate", "private"} <= types


@pytest.mark.django_db
def test_legacy_friend_user_renamed_in_place():
    legacy = User.objects.create(
        display_name="A Friend",
        email="friend@demo.example",
        reputation=10,
        password=make_password(DEMO_PASSWORD),
    )
    data = build_boston_demo()
    legacy.refresh_from_db()
    assert legacy.email == "running.friend@demo.example"
    assert legacy.display_name == "A Running Friend"
    assert data["running_friend"].id == legacy.id  # renamed, not duplicated
    assert User.objects.filter(email="friend@demo.example").count() == 0


@pytest.mark.django_db
def test_seed_personas_can_log_in():
    data = build_boston_demo()
    for key, email in [
        ("owner", "owner@demo.example"),
        ("running_friend", "running.friend@demo.example"),
        ("dimsum_friend", "dimsum.friend@demo.example"),
        ("runner", "runner@demo.example"),
        ("local", "local@demo.example"),
    ]:
        assert data[key].email == email
        assert check_password(DEMO_PASSWORD, data[key].password)


@pytest.mark.django_db
def test_seed_is_idempotent():
    build_boston_demo()
    counts = (Note.objects.count(), User.objects.count())
    build_boston_demo()
    assert (Note.objects.count(), User.objects.count()) == counts


def test_seed_demo_refresh_rebuilds_seed_only(db):
    from django.core.management import call_command

    data = build_boston_demo()
    seed_count = Note.objects.filter(is_seed=True).count()
    assert seed_count > 0
    user_note = Note.objects.create(
        tenant=data["tenant"],
        map=data["map"],
        author=data["running_friend"],
        title="a visitor's pin",
        point=Point(-71.06, 42.35),
        is_seed=False,
    )
    call_command("seed_demo", "--refresh")
    assert Note.objects.filter(is_seed=True).count() == seed_count
    assert Note.objects.filter(id=user_note.id).exists()


def test_china_pearl_is_friends_only_with_dimsum_take(db):
    data = build_boston_demo()
    pin = data["notes_by_slug"]["china-pearl"]
    sections = list(pin.sections.all())
    assert len(sections) == 1 and sections[0].rule_type == "audience"
    assert set(sections[0].rule_params["user_ids"]) == {
        str(data["running_friend"].id),
        str(data["dimsum_friend"].id),
    }
    appends = list(pin.appends.all())
    assert len(appends) == 1
    assert appends[0].author_id == data["dimsum_friend"].id


def test_shipped_seed_file_validates():
    from maps.seed import SEED_PATH
    from maps.seed_schema import load_seed_file

    seed = load_seed_file(SEED_PATH)  # no raise = the shipped file is valid
    assert len(seed.top_level) >= 4
