import json
from typing import Any

import pytest

from maps.seed_schema import SeedValidationError, load_seed_file


def _write(tmp_path, doc):
    p = tmp_path / "seed.geojson"
    p.write_text(json.dumps(doc))
    return p


def _feature(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-71.06, 42.36]},
        "properties": {
            "slug": "a-pin",
            "title": "A pin",
            "author": "local",
            "sections": [{"rule": "public", "content": "hello"}],
        },
    }
    base["geometry"] = over.pop("geometry", base["geometry"])
    base["properties"] = {**base["properties"], **over}
    return base


def _doc(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def test_minimal_valid_file_loads(tmp_path):
    seed = load_seed_file(_write(tmp_path, _doc(_feature())))
    assert len(seed.top_level) == 1 and seed.appends == []


def test_unknown_property_rejected(tmp_path):
    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(_feature(surprise="x"))))


def test_unknown_author_rejected(tmp_path):
    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(_feature(author="mallory"))))


def test_duplicate_slug_rejected(tmp_path):
    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(_feature(), _feature())))


def test_append_requires_null_geometry_and_no_title(tmp_path):
    parent = _feature()
    ok: dict[str, Any] = {
        "type": "Feature",
        "geometry": None,
        "properties": {
            "slug": "a-take",
            "author": "runner",
            "parent": "a-pin",
            "sections": [{"rule": "public", "content": "yes"}],
        },
    }
    seed = load_seed_file(_write(tmp_path, _doc(parent, ok)))
    assert [f.properties.slug for f in seed.appends] == ["a-take"]
    # geometry on an append is a lie in the file
    bad = {**ok, "geometry": {"type": "Point", "coordinates": [-71.06, 42.36]}}
    bad["properties"] = {**ok["properties"], "slug": "a-take-2"}
    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(parent, bad)))


def test_append_parent_must_resolve(tmp_path):
    orphan = {
        "type": "Feature",
        "geometry": None,
        "properties": {
            "slug": "x",
            "author": "runner",
            "parent": "nope",
            "sections": [{"rule": "public", "content": "hi"}],
        },
    }
    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(orphan)))


def test_out_of_bbox_coordinate_rejected(tmp_path):
    nyc = _feature(geometry={"type": "Point", "coordinates": [-74.0, 40.7]})
    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(nyc)))


def test_transposed_lng_lat_rejected(tmp_path):
    swapped = _feature(geometry={"type": "Point", "coordinates": [42.36, -71.06]})
    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(swapped)))


def test_polygon_must_be_closed(tmp_path):
    open_ring = _feature(
        geometry={
            "type": "Polygon",
            "coordinates": [
                [[-71.07, 42.35], [-71.06, 42.36], [-71.05, 42.35]]  # not closed
            ],
        }
    )
    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(open_ring)))


def test_audience_rule_needs_users_or_groups(tmp_path):
    bare = _feature(sections=[{"rule": "audience", "content": "x"}])
    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(bare)))


def test_attribute_gate_needs_attribute_and_threshold(tmp_path):
    ok = _feature(
        sections=[
            {"rule": "attribute_gate", "attribute": "reputation", "threshold": 50, "content": "x"}
        ]
    )
    load_seed_file(_write(tmp_path, _doc(ok)))  # no raise
    bad = _feature(sections=[{"rule": "attribute_gate", "content": "x"}])
    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(bad)))


def test_public_rule_forbids_targeting_fields(tmp_path):
    bad = _feature(sections=[{"rule": "public", "users": ["local"], "content": "x"}])
    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(bad)))


def test_duplicate_author_title_rejected(tmp_path):
    a = _feature()
    b = _feature(slug="a-pin-2")  # same author + title as a
    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(a, b)))


def test_one_append_per_author_parent(tmp_path):
    parent = _feature()

    def take(slug):
        return {
            "type": "Feature",
            "geometry": None,
            "properties": {
                "slug": slug,
                "author": "runner",
                "parent": "a-pin",
                "sections": [{"rule": "public", "content": "hi"}],
            },
        }

    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(parent, take("t1"), take("t2"))))
