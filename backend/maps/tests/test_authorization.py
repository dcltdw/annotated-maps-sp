import pytest
from django.test import Client

from maps.seed import build_boston_demo


@pytest.fixture(autouse=True)
def _sandbox(settings):
    settings.SANDBOX_MODE = True


@pytest.fixture
def demo(db):
    return build_boston_demo()


def _visible_contents(map_id, preview_as=None):
    url = f"/api/v1/maps/{map_id}/notes"
    if preview_as:
        url += f"?preview_as={preview_as}"
    notes = Client().get(url).json()
    note = next(n for n in notes if n["title"].startswith("Castle Island"))
    return {s["content"] for s in note["sections"] if s["visibility"] == "visible"}


def test_guest_sees_only_public(demo):
    contents = _visible_contents(demo["map"].id)
    assert any("scenic" in c for c in contents)  # public
    assert not any("Parking fills" in c for c in contents)  # audience(friend) hidden
    assert not any("knee" in c for c in contents)  # private hidden


def test_private_never_leaks_to_a_non_owner(demo):
    for persona in ("running_friend", "dimsum_friend", "runner", "local"):
        contents = _visible_contents(demo["map"].id, demo[persona].id)
        assert not any("knee" in c for c in contents), f"private leaked to {persona}"


def test_audience_friend_sees_the_parking_tip(demo):
    contents = _visible_contents(demo["map"].id, demo["running_friend"].id)
    assert any("Parking fills" in c for c in contents)


def test_non_member_does_not_see_running_club_section_but_gets_a_teaser(demo):
    url = f"/api/v1/maps/{demo['map'].id}/notes?preview_as={demo['dimsum_friend'].id}"
    notes = Client().get(url).json()
    note = next(n for n in notes if n["title"].startswith("Castle Island"))
    club_sections = [s for s in note["sections"] if s["content"] and "Sullivan" in s["content"]]
    assert club_sections == []  # not visible to a non-member
    assert any(s["visibility"] == "teaser" for s in note["sections"])  # but teased (opt-in)


def test_running_club_member_sees_the_club_section(demo):
    contents = _visible_contents(demo["map"].id, demo["runner"].id)
    assert any("Sullivan" in c for c in contents)


def test_reputation_gate_opens_only_at_threshold(demo):
    # running_friend has rep 10 (below threshold 50) — gate closed
    assert not any(
        "ices over" in c for c in _visible_contents(demo["map"].id, demo["running_friend"].id)
    )
    # local has rep 60 (above threshold 50) — gate open
    assert any("ices over" in c for c in _visible_contents(demo["map"].id, demo["local"].id))


def test_owner_sees_everything(demo):
    contents = _visible_contents(demo["map"].id, demo["owner"].id)
    for needle in ("scenic", "Parking fills", "Sullivan", "ices over", "knee"):
        assert any(needle in c for c in contents), f"owner missing {needle!r}"
