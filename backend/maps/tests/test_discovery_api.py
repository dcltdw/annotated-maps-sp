from uuid import uuid4

import pytest
from django.test import Client

from maps.seed import build_boston_demo


@pytest.fixture
def demo(db):
    return build_boston_demo()


def test_maps_list_returns_boston(demo):
    maps = Client().get("/api/v1/maps").json()
    boston = next(m for m in maps if "Boston" in m["name"])
    assert "lng" in boston and "lat" in boston and "zoom" in boston


def test_viewers_list_includes_all_personas(demo):
    url = f"/api/v1/maps/{demo['map'].id}/viewers"
    names = {v["display_name"] for v in Client().get(url).json()}
    assert {"You (owner)", "A Friend", "Run-club Member", "Reputable Local"} <= names


def test_viewers_unknown_map_returns_404(demo):
    resp = Client().get(f"/api/v1/maps/{uuid4()}/viewers")
    assert resp.status_code == 404


def test_groups_list_returns_tenant_groups(demo):
    names = {g["name"] for g in Client().get(f"/api/v1/maps/{demo['map'].id}/groups").json()}
    assert "Running club" in names
