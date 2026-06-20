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
