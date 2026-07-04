# Richer Demo Seed Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 4-note hand-coded demo seed with ~33 curated notes (+5 appends) authored as a schema-validated GeoJSON file, including the persona split (A Running Friend / A Dim Sum Friend), the Dim sum crew group, and a `seed_preview` validate+visualize command.

**Architecture:** Seed content lives in `backend/maps/seed_data.geojson` (a GeoJSON FeatureCollection); `backend/maps/seed_schema.py` (Pydantic, already available via django-ninja) validates it; `backend/maps/seed.py` keeps the cast in code and gains a typed loader that resolves symbolic keys (persona/group names) to database rows. `seed_demo --refresh` machinery is unchanged.

**Tech Stack:** Django 5 + GeoDjango (GEOS), Pydantic v2 (via django-ninja — NO new dependency), pytest, Leaflet-via-CDN in a generated static HTML (dev tool only).

**Spec:** `docs/superpowers/specs/2026-07-04-richer-seed-data-design.md` — read it before starting any task.

## Global Constraints

- All backend commands run from `backend/`: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .` — ALL must pass before every commit. (Local macOS: `backend/.env` needs `GDAL_LIBRARY_PATH=/usr/local/lib/libgdal.dylib`; DB via `docker compose up -d db`, wait for `pg_isready`.)
- No new Python dependencies. Pydantic comes with django-ninja>=1.3.
- Persona keys (exact): `owner`, `running-friend`, `dimsum-friend`, `runner`, `local`. Group keys: `running-club`, `dim-sum-crew`.
- Persona emails: `owner@demo.example`, `running.friend@demo.example`, `dimsum.friend@demo.example`, `runner@demo.example`, `local@demo.example`. Password for all: `DEMO_PASSWORD = "demo-pass-12345"` (unchanged).
- Friend-tier sections always target BOTH friends: `"users": ["running-friend", "dimsum-friend"]`.
- Bounding box (geometry lint): lng −71.20…−70.90, lat 42.25…42.45.
- Content register: real place names, real coordinates, fictional-but-plausible tips. Never invent hours/prices/claims a visitor could act on to their detriment. Match the existing voice (see current `seed.py` strings).
- The showcase note is titled exactly `Charles River loop` and must keep all four rule types (public, audience×2, attribute_gate, private) — see spec §"Showcase invariant".
- `rule_params` written to the DB use string UUIDs: `{"user_ids": [...]}` / `{"group_ids": [...]}` (existing convention, see current `seed.py`).

## File Structure

- Create: `backend/maps/seed_schema.py` — Pydantic models + `load_seed_file()` + geometry lint. Single validation implementation used by loader, tests, and preview.
- Create: `backend/maps/seed_data.geojson` — all note content.
- Create: `backend/maps/tests/test_seed_schema.py` — schema unit tests + "shipped file validates" test.
- Modify: `backend/maps/seed.py` — cast (5 personas, 2 groups, rename migration) + typed loader; delete the hand-coded note blocks.
- Modify: `backend/maps/tests/test_seed.py` — rewrite for the new cast/return contract; add rename-migration + showcase-invariant tests.
- Create: `backend/maps/management/commands/seed_preview.py` — validate + HTML preview.
- Create: `backend/maps/tests/test_seed_preview.py`.
- Modify: `.gitignore` (repo root) — add `seed_preview.html`.
- Modify: `frontend/src/locales/en.json:86` — `auth.demoHint` email.
- Modify: `frontend/e2e/session-expiry.spec.ts:17` — USER fixture email + display name.

---

### Task 1: Pydantic seed schema (`seed_schema.py`)

**Files:**
- Create: `backend/maps/seed_schema.py`
- Test: `backend/maps/tests/test_seed_schema.py`

**Interfaces:**
- Produces: `load_seed_file(path: Path) -> SeedFile` (raises `SeedValidationError` on any violation); `SeedFile.top_level` / `SeedFile.appends` properties returning `list[SeedFeature]`; `SeedFeature.properties: SeedProps` with fields `slug: str`, `title: str | None`, `author: str`, `parent: str | None`, `docs: str | None`, `sections: list[SeedSection]`; `SeedSection` fields `rule`, `content`, `users`, `groups`, `attribute`, `threshold`, `teaser`; geometry union `PointGeom | LineGeom | PolygonGeom | None` with `.type` discriminator and `.coordinates`.
- Constants: `PERSONA_KEYS`, `GROUP_KEYS`, `BBOX`, `SHOWCASE_TITLE = "Charles River loop"`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/maps/tests/test_seed_schema.py
import json

import pytest

from maps.seed_schema import SeedValidationError, load_seed_file


def _write(tmp_path, doc):
    p = tmp_path / "seed.geojson"
    p.write_text(json.dumps(doc))
    return p


def _feature(**over):
    base = {
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
    ok = {
        "type": "Feature",
        "geometry": None,
        "properties": {
            "slug": "a-take", "author": "runner", "parent": "a-pin",
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
        "type": "Feature", "geometry": None,
        "properties": {"slug": "x", "author": "runner", "parent": "nope",
                       "sections": [{"rule": "public", "content": "hi"}]},
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
    open_ring = _feature(geometry={"type": "Polygon", "coordinates": [
        [[-71.07, 42.35], [-71.06, 42.36], [-71.05, 42.35]]  # not closed
    ]})
    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(open_ring)))


def test_audience_rule_needs_users_or_groups(tmp_path):
    bare = _feature(sections=[{"rule": "audience", "content": "x"}])
    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(bare)))


def test_attribute_gate_needs_attribute_and_threshold(tmp_path):
    ok = _feature(sections=[{"rule": "attribute_gate", "attribute": "reputation",
                             "threshold": 50, "content": "x"}])
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
        return {"type": "Feature", "geometry": None,
                "properties": {"slug": slug, "author": "runner", "parent": "a-pin",
                               "sections": [{"rule": "public", "content": "hi"}]}}
    with pytest.raises(SeedValidationError):
        load_seed_file(_write(tmp_path, _doc(parent, take("t1"), take("t2"))))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest maps/tests/test_seed_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'maps.seed_schema'`

- [ ] **Step 3: Implement `seed_schema.py`**

```python
# backend/maps/seed_schema.py
"""Schema + lint for backend/maps/seed_data.geojson.

Single validation implementation shared by the seed loader, the CI tests,
and the seed_preview command. See docs/superpowers/specs/
2026-07-04-richer-seed-data-design.md.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PERSONA_KEYS = ("owner", "running-friend", "dimsum-friend", "runner", "local")
GROUP_KEYS = ("running-club", "dim-sum-crew")
BBOX = {"min_lng": -71.20, "max_lng": -70.90, "min_lat": 42.25, "max_lat": 42.45}
SHOWCASE_TITLE = "Charles River loop"  # demo-tour contract; see the tour spec

PersonaKey = Literal["owner", "running-friend", "dimsum-friend", "runner", "local"]
GroupKey = Literal["running-club", "dim-sum-crew"]
LngLat = tuple[float, float]


class SeedValidationError(ValueError):
    """Any structural or lint violation in a seed file."""


def _check_bounds(points: list[LngLat]) -> None:
    for lng, lat in points:
        if not (BBOX["min_lng"] <= lng <= BBOX["max_lng"]):
            raise ValueError(f"longitude {lng} outside Greater Boston bbox")
        if not (BBOX["min_lat"] <= lat <= BBOX["max_lat"]):
            raise ValueError(f"latitude {lat} outside Greater Boston bbox")


class PointGeom(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["Point"]
    coordinates: LngLat

    @model_validator(mode="after")
    def _bounds(self) -> "PointGeom":
        _check_bounds([self.coordinates])
        return self


class LineGeom(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["LineString"]
    coordinates: list[LngLat] = Field(min_length=2)

    @model_validator(mode="after")
    def _bounds(self) -> "LineGeom":
        _check_bounds(self.coordinates)
        return self


class PolygonGeom(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["Polygon"]
    coordinates: list[list[LngLat]] = Field(min_length=1, max_length=1)  # exterior ring only

    @model_validator(mode="after")
    def _ring(self) -> "PolygonGeom":
        ring = self.coordinates[0]
        if len(ring) < 4:
            raise ValueError("polygon ring needs >= 4 points")
        if ring[0] != ring[-1]:
            raise ValueError("polygon ring is not closed (first != last)")
        _check_bounds(ring)
        return self


Geometry = Annotated[Union[PointGeom, LineGeom, PolygonGeom], Field(discriminator="type")]


class SeedSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule: Literal["public", "audience", "attribute_gate", "private"]
    content: str = Field(min_length=1)
    users: list[PersonaKey] | None = None
    groups: list[GroupKey] | None = None
    attribute: Literal["reputation"] | None = None
    threshold: int | None = None
    teaser: bool = False

    @model_validator(mode="after")
    def _rule_shape(self) -> "SeedSection":
        targeting = self.users is not None or self.groups is not None
        gating = self.attribute is not None or self.threshold is not None
        if self.rule == "audience":
            if not targeting:
                raise ValueError("audience section needs users and/or groups")
            if gating:
                raise ValueError("audience section cannot carry attribute/threshold")
        elif self.rule == "attribute_gate":
            if self.attribute is None or self.threshold is None:
                raise ValueError("attribute_gate needs attribute and threshold")
            if targeting:
                raise ValueError("attribute_gate cannot carry users/groups")
        else:  # public / private
            if targeting or gating:
                raise ValueError(f"{self.rule} section cannot carry targeting fields")
        return self


class SeedProps(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    author: PersonaKey
    sections: list[SeedSection] = Field(min_length=1)
    title: str | None = None
    parent: str | None = None
    docs: str | None = None  # the whitelisted documentation field (spec §1)


class SeedFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["Feature"]
    geometry: Geometry | None
    properties: SeedProps

    @model_validator(mode="after")
    def _append_shape(self) -> "SeedFeature":
        is_append = self.properties.parent is not None
        if is_append:
            if self.geometry is not None:
                raise ValueError(f"append {self.properties.slug!r} must have null geometry")
            if self.properties.title is not None:
                raise ValueError(f"append {self.properties.slug!r} must not carry a title")
        else:
            if self.geometry is None:
                raise ValueError(f"top-level {self.properties.slug!r} needs geometry")
            if self.properties.title is None:
                raise ValueError(f"top-level {self.properties.slug!r} needs a title")
        return self


class SeedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["FeatureCollection"]
    features: list[SeedFeature] = Field(min_length=1)

    @model_validator(mode="after")
    def _cross_feature(self) -> "SeedFile":
        slugs = [f.properties.slug for f in self.features]
        if len(slugs) != len(set(slugs)):
            raise ValueError("duplicate slugs in seed file")
        top_titles = set()
        append_keys = set()
        top_slugs = {f.properties.slug for f in self.features if f.properties.parent is None}
        for f in self.features:
            p = f.properties
            if p.parent is None:
                key = (p.author, p.title)
                if key in top_titles:
                    raise ValueError(f"duplicate (author, title): {key}")
                top_titles.add(key)
            else:
                if p.parent not in top_slugs:
                    raise ValueError(f"append {p.slug!r} references unknown parent {p.parent!r}")
                akey = (p.author, p.parent)
                if akey in append_keys:
                    raise ValueError(f"two appends by {p.author!r} on {p.parent!r}")
                append_keys.add(akey)
        return self

    @property
    def top_level(self) -> list[SeedFeature]:
        return [f for f in self.features if f.properties.parent is None]

    @property
    def appends(self) -> list[SeedFeature]:
        return [f for f in self.features if f.properties.parent is not None]


def load_seed_file(path: Path) -> SeedFile:
    """Parse + validate a seed GeoJSON file. Raises SeedValidationError."""
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SeedValidationError(f"{path.name}: not valid JSON: {exc}") from exc
    try:
        return SeedFile.model_validate(raw)
    except ValidationError as exc:
        raise SeedValidationError(f"{path.name}: {exc}") from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest maps/tests/test_seed_schema.py -v`
Expected: all PASS

- [ ] **Step 5: Full gate, then commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`
Expected: all green (note: full pytest needs the PostGIS container up)

```bash
git add maps/seed_schema.py maps/tests/test_seed_schema.py
git commit -m "feat: Pydantic schema + lint for GeoJSON seed data"
```

---

### Task 2: Cast rebuild + typed loader (existing 4 notes as GeoJSON)

**Files:**
- Create: `backend/maps/seed_data.geojson` (the 4 existing notes + 1 append, converted)
- Modify: `backend/maps/seed.py` (full rewrite of note-building; cast gains the persona split + Dim sum crew + rename migration)
- Modify: `backend/maps/tests/test_seed.py` (rewrite for new contract)

**Interfaces:**
- Consumes: `load_seed_file`, `SeedFile`, section/geometry models from Task 1.
- Produces: `build_boston_demo() -> dict` returning keys `tenant`, `map`, `owner`, `running_friend`, `dimsum_friend`, `runner`, `local`, `running_club`, `dim_sum_crew`, `notes_by_slug: dict[str, Note]`. `SEED_PATH: Path` module constant. (The old `friend`/`club`/`note`/`area_note`/`route_note`/`china_pearl` keys are GONE — anything referencing them must be updated in this task.)

- [ ] **Step 1: Convert the existing content to `seed_data.geojson`**

Create `backend/maps/seed_data.geojson` containing exactly the current five entries, re-expressed (new persona keys; friend-tier targets BOTH friends; China Pearl append re-authored to `dimsum-friend`; showcase `docs` marker on the loop). Full file:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {"type": "Point", "coordinates": [-71.0136, 42.3380]},
      "properties": {
        "slug": "castle-island-loop",
        "title": "Castle Island — Pleasure Bay Loop",
        "author": "owner",
        "sections": [
          {"rule": "public", "content": "Flat, scenic ~2.5-mi loop around the bay. Great easy day."},
          {"rule": "audience", "users": ["running-friend", "dimsum-friend"], "content": "Parking fills by 9am — use the far lot by the fort."},
          {"rule": "audience", "groups": ["running-club"], "teaser": true, "content": "Water fountain + restrooms by the fort; Sullivan's sells water & Gatorade."},
          {"rule": "attribute_gate", "attribute": "reputation", "threshold": 50, "content": "Trusted-local tip: the back stretch ices over first in winter."},
          {"rule": "private", "content": "Reminder: right knee twinges on the back stretch — ease off."}
        ]
      }
    },
    {
      "type": "Feature",
      "geometry": {"type": "Polygon", "coordinates": [[[-71.0723, 42.3539], [-71.0699, 42.3551], [-71.0685, 42.3537], [-71.0709, 42.3525], [-71.0723, 42.3539]]]},
      "properties": {
        "slug": "boston-public-garden",
        "title": "Boston Public Garden",
        "author": "local",
        "sections": [
          {"rule": "public", "content": "Swan boats + the willows. Calm loop, good for an easy shakeout."},
          {"rule": "audience", "users": ["running-friend", "dimsum-friend"], "content": "Meet by the Make Way for Ducklings statues — easy landmark."},
          {"rule": "audience", "groups": ["running-club"], "teaser": true, "content": "Club shakeout: two laps of the lagoon path, then out onto the Common."},
          {"rule": "attribute_gate", "attribute": "reputation", "threshold": 50, "content": "Local tip: the Arlington St gate opens earliest — quietest before 8am."},
          {"rule": "private", "content": "Note to self: confirm the swan boats are running before recommending."}
        ]
      }
    },
    {
      "type": "Feature",
      "geometry": {"type": "LineString", "coordinates": [[-71.0920, 42.3578], [-71.0880, 42.3596], [-71.0840, 42.3610], [-71.0805, 42.3627], [-71.0793, 42.3641], [-71.0745, 42.3628], [-71.0707, 42.3611], [-71.0745, 42.3573], [-71.0800, 42.3546], [-71.0858, 42.3525], [-71.0905, 42.3517], [-71.0913, 42.3548], [-71.0920, 42.3578]]},
      "properties": {
        "slug": "charles-river-loop",
        "title": "Charles River loop",
        "author": "runner",
        "docs": "TOUR SHOWCASE — the demo tour opens this note by title. Keep the title and the full rule spread. See docs/superpowers/specs/2026-07-04-demo-tour-design.md before editing.",
        "sections": [
          {"rule": "public", "content": "Flat ~4.5 km loop: east along Memorial Drive, over the Longfellow Bridge, back along the Esplanade, closing across the Mass Ave bridge. Water fountains near both bridges."},
          {"rule": "audience", "users": ["running-friend", "dimsum-friend"], "content": "Start from the Mass Ave bridge so you finish with the Esplanade views."},
          {"rule": "audience", "groups": ["running-club"], "teaser": true, "content": "Club tempo: pick it up between the bridges, float the bridge climbs."},
          {"rule": "attribute_gate", "attribute": "reputation", "threshold": 50, "content": "Trusted tip: the Esplanade puddles near the lagoon after heavy rain."},
          {"rule": "private", "content": "Reminder: refill at the Longfellow fountain — the Mass Ave one is often off."}
        ]
      }
    },
    {
      "type": "Feature",
      "geometry": {"type": "Point", "coordinates": [-71.0600, 42.3514]},
      "properties": {
        "slug": "china-pearl",
        "title": "China Pearl",
        "author": "owner",
        "sections": [
          {"rule": "audience", "users": ["running-friend", "dimsum-friend"], "content": "Favorite dim sum place."}
        ]
      }
    },
    {
      "type": "Feature",
      "geometry": null,
      "properties": {
        "slug": "china-pearl-take",
        "author": "dimsum-friend",
        "parent": "china-pearl",
        "sections": [
          {"rule": "public", "content": "Best shumai in town!"}
        ]
      }
    }
  ]
}
```

- [ ] **Step 2: Write the failing tests (rewrite `test_seed.py`)**

Replace the whole file:

```python
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
        "castle-island-loop", "boston-public-garden", "charles-river-loop", "china-pearl",
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
        str(data["running_friend"].id), str(data["dimsum_friend"].id),
    }


@pytest.mark.django_db
def test_showcase_invariant():
    """The demo tour opens this note by title — see the demo-tour spec.

    If this test fails you are editing the TOUR SHOWCASE: re-read
    docs/superpowers/specs/2026-07-04-demo-tour-design.md before proceeding.
    """
    from maps.seed_schema import SHOWCASE_TITLE

    data = build_boston_demo()
    note = Note.objects.get(title=SHOWCASE_TITLE, parent__isnull=True)
    assert note.path is not None  # it's the route, center-viewport
    types = set(note.sections.values_list("rule_type", flat=True))
    assert {"public", "audience", "attribute_gate", "private"} <= types


@pytest.mark.django_db
def test_legacy_friend_user_renamed_in_place():
    legacy = User.objects.create(
        display_name="A Friend", email="friend@demo.example",
        reputation=10, password=make_password(DEMO_PASSWORD),
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
        tenant=data["tenant"], map=data["map"], author=data["running_friend"],
        title="a visitor's pin", point=Point(-71.06, 42.35), is_seed=False,
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
        str(data["running_friend"].id), str(data["dimsum_friend"].id),
    }
    appends = list(pin.appends.all())
    assert len(appends) == 1
    assert appends[0].author_id == data["dimsum_friend"].id


def test_shipped_seed_file_validates():
    from maps.seed import SEED_PATH
    from maps.seed_schema import load_seed_file

    seed = load_seed_file(SEED_PATH)  # no raise = the shipped file is valid
    assert len(seed.top_level) >= 4
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest maps/tests/test_seed.py -v`
Expected: FAIL — `ImportError` (no `SEED_PATH`), then KeyErrors for new cast keys

- [ ] **Step 4: Rewrite `seed.py`**

```python
# backend/maps/seed.py
from __future__ import annotations

from pathlib import Path

from django.contrib.auth.hashers import make_password
from django.contrib.gis.geos import LineString, Point, Polygon

from core.models import Group, Membership, Tenant, User
from maps.models import Map, Note, Section
from maps.seed_schema import SeedFeature, SeedSection, load_seed_file

DEMO_PASSWORD = "demo-pass-12345"  # public demo credential, surfaced in the UI hint
SEED_PATH = Path(__file__).with_name("seed_data.geojson")

# key -> (display_name, email, reputation)
_PERSONAS = {
    "owner": ("You (owner)", "owner@demo.example", 100),
    "running-friend": ("A Running Friend", "running.friend@demo.example", 10),
    "dimsum-friend": ("A Dim Sum Friend", "dimsum.friend@demo.example", 10),
    "runner": ("Run-club Member", "runner@demo.example", 30),
    "local": ("Reputable Local", "local@demo.example", 60),
}
# group key -> (name, member persona keys)
_GROUPS = {
    "running-club": ("Running club", ["runner", "running-friend"]),
    "dim-sum-crew": ("Dim sum crew", ["dimsum-friend"]),
}


def _migrate_legacy_friend() -> None:
    # Pre-split deployments have "A Friend" <friend@demo.example>. Rename in place so
    # authored content survives and no stale persona lingers in the viewer switcher.
    User.objects.filter(email="friend@demo.example").update(
        display_name="A Running Friend", email="running.friend@demo.example"
    )


def _build_cast() -> tuple[Tenant, Map, dict[str, User], dict[str, Group]]:
    tenant, _ = Tenant.objects.get_or_create(slug="boston", defaults={"name": "Boston Demo"})
    _migrate_legacy_friend()
    users: dict[str, User] = {}
    for key, (name, email, rep) in _PERSONAS.items():
        user, _ = User.objects.get_or_create(
            email=email,
            defaults={
                "display_name": name,
                "reputation": rep,
                "password": make_password(DEMO_PASSWORD),
            },
        )
        users[key] = user
    for key, user in users.items():
        role = Membership.Role.OWNER if key == "owner" else Membership.Role.CONTRIBUTOR
        Membership.objects.get_or_create(user=user, tenant=tenant, defaults={"role": role})
    groups: dict[str, Group] = {}
    for key, (name, member_keys) in _GROUPS.items():
        group, _ = Group.objects.get_or_create(tenant=tenant, name=name)
        group.members.set([users[k] for k in member_keys])
        groups[key] = group
    the_map, _ = Map.objects.get_or_create(
        tenant=tenant,
        name="Greater Boston",
        defaults={"center": Point(-71.0589, 42.3601), "default_zoom": 12},
    )
    return tenant, the_map, users, groups


def _geometry_fields(feature: SeedFeature) -> dict:
    geom = feature.geometry
    if geom is None:  # append — no anchor by design
        return {}
    if geom.type == "Point":
        return {"point": Point(*geom.coordinates)}
    if geom.type == "LineString":
        return {"path": LineString([tuple(c) for c in geom.coordinates])}
    return {"area": Polygon([tuple(c) for c in geom.coordinates[0]])}


def _rule_params(section: SeedSection, users: dict[str, User], groups: dict[str, Group]) -> dict:
    if section.rule == "audience":
        params: dict = {}
        if section.users:
            params["user_ids"] = [str(users[k].id) for k in section.users]
        if section.groups:
            params["group_ids"] = [str(groups[k].id) for k in section.groups]
        return params
    if section.rule == "attribute_gate":
        return {"attribute": section.attribute, "threshold": section.threshold}
    return {}


def _create_sections(
    note: Note, sections: list[SeedSection], users: dict[str, User], groups: dict[str, Group]
) -> None:
    Section.objects.bulk_create(
        [
            Section(
                note=note,
                order=i,
                rule_type=s.rule,
                rule_params=_rule_params(s, users, groups),
                teaser=s.teaser,
                content=s.content,
            )
            for i, s in enumerate(sections)
        ]
    )


def build_boston_demo() -> dict:
    tenant, the_map, users, groups = _build_cast()
    seed = load_seed_file(SEED_PATH)

    notes_by_slug: dict[str, Note] = {}
    for feature in seed.top_level:
        props = feature.properties
        note, created = Note.objects.get_or_create(
            tenant=tenant,
            map=the_map,
            author=users[props.author],
            title=props.title,
            defaults={"is_seed": True, **_geometry_fields(feature)},
        )
        if created:
            _create_sections(note, props.sections, users, groups)
        notes_by_slug[props.slug] = note

    for feature in seed.appends:
        props = feature.properties
        append, created = Note.objects.get_or_create(
            tenant=tenant,
            map=the_map,
            author=users[props.author],
            parent=notes_by_slug[props.parent],
            defaults={"is_seed": True},
        )
        if created:
            _create_sections(append, props.sections, users, groups)
        notes_by_slug[props.slug] = append

    return {
        "tenant": tenant,
        "map": the_map,
        "owner": users["owner"],
        "running_friend": users["running-friend"],
        "dimsum_friend": users["dimsum-friend"],
        "runner": users["runner"],
        "local": users["local"],
        "running_club": groups["running-club"],
        "dim_sum_crew": groups["dim-sum-crew"],
        "notes_by_slug": notes_by_slug,
    }
```

Note: the top-level `get_or_create` key `(tenant, map, author, title)` cannot collide with appends — schema guarantees top-level titles are non-empty strings while appends carry no title (model default `""`). Do not add `parent__isnull` to the lookup (a `__` lookup inside `get_or_create` breaks the create path).

- [ ] **Step 5: Check for other references to the old return keys**

Run: `grep -rn "build_boston_demo\|data\[\"friend\"\]\|data\['friend'\]" --include="*.py" | grep -v seed`
Expected: any hits outside `maps/seed.py` / `maps/tests/test_seed.py` (e.g. other test fixtures/conftest) must be updated to the new keys (`running_friend`, `notes_by_slug`, etc.) in this task. Search also for `"A Friend"` in backend tests.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest maps/tests/test_seed.py maps/tests/test_seed_schema.py -v`, then the FULL suite `uv run pytest` (visibility/API tests must still pass — they build on the seed).
Expected: all PASS

- [ ] **Step 7: Full gate, then commit**

```bash
git add maps/seed.py maps/seed_data.geojson maps/tests/test_seed.py
git commit -m "feat: GeoJSON-driven seed loader, persona split, Dim sum crew"
```

---

### Task 3: Content expansion to ~33 notes + 5 appends

**Files:**
- Modify: `backend/maps/seed_data.geojson` (append the new features)
- Modify: `backend/maps/tests/test_seed.py` (add count/mix assertions)

**Interfaces:**
- Consumes: the Task 2 file format; nothing new produced — this is content.

- [ ] **Step 1: Add count/mix tests first**

Append to `test_seed.py`:

```python
def test_seed_content_mix(db):
    from maps.seed import SEED_PATH
    from maps.seed_schema import load_seed_file

    seed = load_seed_file(SEED_PATH)
    top = seed.top_level
    assert 30 <= len(top) <= 38
    assert 4 <= len(seed.appends) <= 6
    # Geometry variety
    kinds = [f.geometry.type for f in top]
    assert kinds.count("LineString") >= 5   # existing loop + 4 new routes
    assert kinds.count("Polygon") >= 5      # existing garden + 4 new areas
    # Texture: majority simple (<=2 sections), a handful of full ladders
    simple = [f for f in top if len(f.properties.sections) <= 2]
    full = [
        f for f in top
        if {"public", "audience", "attribute_gate", "private"}
        <= {s.rule for s in f.properties.sections}
    ]
    assert len(simple) >= len(top) * 0.5
    assert 4 <= len(full) <= 6
    # Every persona authors something
    assert {f.properties.author for f in seed.features} == {
        "owner", "running-friend", "dimsum-friend", "runner", "local",
    }
    # At least one whole-note group-gated entry (all sections group-audience)
    gated = [
        f for f in top
        if all(s.rule == "audience" and s.groups for s in f.properties.sections)
    ]
    assert len(gated) >= 1
```

Run: `uv run pytest maps/tests/test_seed.py::test_seed_content_mix -v` → Expected: FAIL (counts too low)

- [ ] **Step 2: Author the new features**

Add the features below to `seed_data.geojson`. The table is the requirement: slug, title, author, geometry (coordinates given), and section profile are **exact**; the section prose is authored at execution following the Global Constraints register (match the existing voice; 1–2 punchy sentences per section). Section profiles: **P** = public only; **P+F** = public + audience(users: both friends); **P+C** = public + audience(groups: running-club); **P+D** = public + audience(groups: dim-sum-crew); **P+R** = public + attribute_gate(reputation, 50); **FULL** = five-tier ladder (public, audience users-both-friends, audience group [running-club unless noted], attribute_gate 50, private); **C-only** = single section, audience(groups: running-club).

| slug | title | author | geometry | profile |
|---|---|---|---|---|
| winsor-dim-sum | Winsor Dim Sum Cafe | dimsum-friend | Point [-71.0602, 42.3512] | FULL (group = dim-sum-crew) |
| great-taste-bakery | Great Taste Bakery | dimsum-friend | Point [-71.0607, 42.3502] | P+D |
| taiwan-cafe | Taiwan Cafe | dimsum-friend | Point [-71.0597, 42.3509] | P |
| regina-pizzeria | Regina Pizzeria | local | Point [-71.0566, 42.3654] | P+F |
| mikes-pastry | Mike's Pastry | dimsum-friend | Point [-71.0546, 42.3647] | P |
| modern-pastry | Modern Pastry | local | Point [-71.0552, 42.3641] | P |
| neptune-oyster | Neptune Oyster | local | Point [-71.0561, 42.3633] | P+R |
| union-oyster-house | Union Oyster House | local | Point [-71.0570, 42.3614] | P+R |
| quincy-market | Quincy Market | local | Point [-71.0546, 42.3600] | P+R (rep tip: where locals actually eat) |
| thinking-cup | Thinking Cup | running-friend | Point [-71.0623, 42.3557] | P |
| tatte-beacon-hill | Tatte Beacon Hill | local | Point [-71.0707, 42.3580] | P |
| flour-fort-point | Flour Bakery (Fort Point) | running-friend | Point [-71.0489, 42.3513] | P+F |
| toro-south-end | Toro | local | Point [-71.0805, 42.3369] | P+F |
| harborwalk-southie | Harborwalk — Seaport to Castle Island | runner | LineString [[-71.0430, 42.3535], [-71.0389, 42.3505], [-71.0355, 42.3450], [-71.0330, 42.3405], [-71.0290, 42.3380], [-71.0220, 42.3370], [-71.0136, 42.3380]] | P+C |
| bu-bridge-extension | Esplanade — BU Bridge out-and-back | running-friend | LineString [[-71.0800, 42.3546], [-71.0905, 42.3517], [-71.1005, 42.3512], [-71.1075, 42.3532]] | P+C |
| southwest-corridor | Southwest Corridor path | runner | LineString [[-71.0755, 42.3475], [-71.0790, 42.3430], [-71.0830, 42.3390], [-71.0880, 42.3350], [-71.0950, 42.3300]] | P+F |
| common-garden-shakeout | Common & Garden shakeout | running-friend | LineString [[-71.0656, 42.3554], [-71.0640, 42.3585], [-71.0685, 42.3560], [-71.0709, 42.3525], [-71.0656, 42.3554]] | P |
| boston-common | Boston Common | owner | Polygon [[[-71.0685, 42.3537], [-71.0640, 42.3585], [-71.0620, 42.3570], [-71.0625, 42.3564], [-71.0656, 42.3524], [-71.0685, 42.3537]]] | FULL |
| columbus-park | Christopher Columbus Park | local | Polygon [[[-71.0515, 42.3612], [-71.0495, 42.3627], [-71.0483, 42.3617], [-71.0505, 42.3603], [-71.0515, 42.3612]]] | P+F |
| paul-revere-mall | Paul Revere Mall (the Prado) | local | Polygon [[[-71.0546, 42.3655], [-71.0536, 42.3661], [-71.0531, 42.3655], [-71.0541, 42.3649], [-71.0546, 42.3655]]] | P |
| cambridge-common | Cambridge Common | runner | Polygon [[[-71.1210, 42.3765], [-71.1185, 42.3782], [-71.1165, 42.3765], [-71.1195, 42.3750], [-71.1210, 42.3765]]] | P+C |
| track-tuesdays | Track Tuesdays | runner | Point [-71.0450, 42.3305] | C-only (whole note club-gated: Moakley Park track meetup) |
| longfellow-viewpoint | Longfellow Bridge viewpoint | running-friend | Point [-71.0765, 42.3617] | P |
| acorn-street | Acorn Street | local | Point [-71.0705, 42.3577] | P |
| park-st-tip | Park St — walk, don't ride | local | Point [-71.0625, 42.3564] | P+R |
| frog-pond | Frog Pond | owner | Point [-71.0656, 42.3554] | P |
| esplanade-fountain | Esplanade water fountain | runner | Point [-71.0800, 42.3546] | P+C |
| fan-pier-view | Fan Pier skyline view | running-friend | Point [-71.0430, 42.3535] | P+F |
| steaming-kettle | The Steaming Kettle | local | Point [-71.0597, 42.3589] | P |

Appends (all `geometry: null`, no title):

| slug | parent | author | content angle |
|---|---|---|---|
| regina-take | regina-pizzeria | runner | post-long-run reward slice |
| mikes-vs-modern | mikes-pastry | local | friendly cannoli-rivalry counterpoint |
| loop-extension-take | charles-river-loop | running-friend | "I add the BU bridge extension" (cross-references their route) |
| common-take | boston-common | dimsum-friend | post-dim-sum walk route |

(With `china-pearl-take` from Task 2, appends total 5.)

- [ ] **Step 3: Validate + run tests**

Run: `uv run pytest maps/tests/test_seed.py maps/tests/test_seed_schema.py -v`
Expected: all PASS, including `test_seed_content_mix` and `test_shipped_seed_file_validates` (the schema will mechanically catch any coordinate typo outside the bbox, unclosed ring, or duplicate constraint violation).

- [ ] **Step 4: Full suite + gate, then commit**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy .`

```bash
git add maps/seed_data.geojson maps/tests/test_seed.py
git commit -m "feat: expand demo seed to ~33 curated Boston notes + 5 appends"
```

---

### Task 4: `seed_preview` command

**Files:**
- Create: `backend/maps/management/commands/seed_preview.py`
- Test: `backend/maps/tests/test_seed_preview.py`
- Modify: `.gitignore` (repo root) — add `seed_preview.html`

**Interfaces:**
- Consumes: `load_seed_file`, `SeedValidationError`, `SHOWCASE_TITLE` from Task 1.
- Produces: `uv run python manage.py seed_preview [path] [--out FILE]` — exit 0 + HTML on valid input; `CommandError` on invalid.

- [ ] **Step 1: Write the failing tests**

```python
# backend/maps/tests/test_seed_preview.py
import json

import pytest
from django.core.management import CommandError, call_command


def _valid_doc(content="hello"):
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-71.06, 42.36]},
            "properties": {
                "slug": "a-pin", "title": "A pin", "author": "local",
                "docs": "load-bearing",
                "sections": [{"rule": "public", "content": content}],
            },
        }],
    }


def test_preview_writes_html_for_valid_file(tmp_path):
    src = tmp_path / "seed.geojson"
    src.write_text(json.dumps(_valid_doc()))
    out = tmp_path / "preview.html"
    call_command("seed_preview", str(src), out=str(out))
    html = out.read_text()
    assert "A pin" in html
    assert "load-bearing" in html  # docs badge surfaces


def test_preview_escapes_content(tmp_path):
    src = tmp_path / "seed.geojson"
    src.write_text(json.dumps(_valid_doc(content='<script>alert("x")</script>')))
    out = tmp_path / "preview.html"
    call_command("seed_preview", str(src), out=str(out))
    html = out.read_text()
    assert '<script>alert("x")</script>' not in html  # raw payload must not appear
    assert "&lt;script&gt;" in html                    # escaped form does


def test_preview_fails_on_invalid_file(tmp_path):
    src = tmp_path / "seed.geojson"
    doc = _valid_doc()
    doc["features"][0]["properties"]["author"] = "mallory"
    src.write_text(json.dumps(doc))
    with pytest.raises(CommandError):
        call_command("seed_preview", str(src), out=str(tmp_path / "x.html"))


def test_preview_defaults_to_shipped_seed(tmp_path):
    out = tmp_path / "shipped.html"
    call_command("seed_preview", out=str(out))  # no path arg
    assert "Charles River loop" in out.read_text()
```

Run: `uv run pytest maps/tests/test_seed_preview.py -v` → Expected: FAIL (unknown command)

- [ ] **Step 2: Implement the command**

```python
# backend/maps/management/commands/seed_preview.py
"""Validate a seed GeoJSON file and render a standalone HTML preview map.

Dev tool: `uv run python manage.py seed_preview [path] [--out seed_preview.html]`.
All content strings are HTML-escaped — the tool is safe on untrusted files
(building block for the future GeoJSON import-review feature).
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from maps.seed import SEED_PATH
from maps.seed_schema import SeedValidationError, load_seed_file

_AUTHOR_COLORS = {
    "owner": "#7c3aed", "running-friend": "#059669", "dimsum-friend": "#d97706",
    "runner": "#2563eb", "local": "#dc2626",
}

_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Seed preview</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#map{height:100%;margin:0}.legend{position:absolute;bottom:12px;left:12px;
z-index:1000;background:#fff;padding:8px 12px;font:13px sans-serif;border-radius:6px;
box-shadow:0 1px 4px rgba(0,0,0,.3)}</style></head>
<body><div id="map"></div><div class="legend">__LEGEND__</div>
<script>
var map = L.map('map').setView([42.3601, -71.0589], 13);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  {attribution: '&copy; OpenStreetMap contributors'}).addTo(map);
var FEATURES = __DATA__;
FEATURES.forEach(function (f) {
  var layer;
  if (f.kind === 'Point') {
    layer = L.circleMarker([f.coords[1], f.coords[0]], {radius: 8, color: f.color, fillOpacity: 0.7});
  } else if (f.kind === 'LineString') {
    layer = L.polyline(f.coords.map(function (c) { return [c[1], c[0]]; }), {color: f.color, weight: 4});
  } else {
    layer = L.polygon(f.coords[0].map(function (c) { return [c[1], c[0]]; }), {color: f.color, fillOpacity: 0.25});
  }
  layer.bindPopup(f.popup).addTo(map);
});
</script></body></html>
"""


class Command(BaseCommand):
    help = "Validate a seed GeoJSON file and write an HTML preview map."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", default=str(SEED_PATH))
        parser.add_argument("--out", default="seed_preview.html")

    def handle(self, *args, **options):
        path = Path(options["path"])
        try:
            seed = load_seed_file(path)
        except (SeedValidationError, OSError) as exc:
            raise CommandError(f"INVALID: {exc}") from exc

        by_slug = {f.properties.slug: f for f in seed.features}
        payload = []
        for feature in seed.features:
            props = feature.properties
            geo = feature.geometry or by_slug[props.parent].geometry  # appends plot at parent
            rules = "".join(
                f"<li>{html.escape(s.rule)}"
                + (f" → users: {html.escape(', '.join(s.users))}" if s.users else "")
                + (f" → groups: {html.escape(', '.join(s.groups))}" if s.groups else "")
                + (f" ≥ {s.threshold}" if s.threshold is not None else "")
                + f": {html.escape(s.content)}</li>"
                for s in props.sections
            )
            badge = (
                f"<p>⚠ <b>{html.escape(props.docs)}</b></p>" if props.docs else ""
            )
            kind_label = "append on " + html.escape(props.parent) if props.parent else geo.type
            popup = (
                f"<b>{html.escape(props.title or '(append)')}</b>"
                f"<br>by {html.escape(props.author)} · {kind_label}{badge}<ul>{rules}</ul>"
            )
            payload.append({
                "kind": geo.type,
                "coords": geo.coordinates
                if geo.type != "Point" else list(geo.coordinates),
                "color": _AUTHOR_COLORS[props.author],
                "popup": popup,
            })

        legend = " ".join(
            f'<span style="color:{c}">●</span> {html.escape(k)}'
            for k, c in _AUTHOR_COLORS.items()
        )
        data = json.dumps(payload).replace("</", "<\\/")  # never close the script tag
        out = Path(options["out"])
        out.write_text(_PAGE.replace("__DATA__", data).replace("__LEGEND__", legend))
        self.stdout.write(self.style.SUCCESS(
            f"OK: {len(seed.top_level)} notes, {len(seed.appends)} appends → {out}"
        ))
```

Pydantic model note: `geo.coordinates` for `LineGeom`/`PolygonGeom` contains tuples; `json.dumps` handles tuples as arrays — no conversion needed.

- [ ] **Step 3: Run tests**

Run: `uv run pytest maps/tests/test_seed_preview.py -v` → Expected: all PASS

- [ ] **Step 4: Gitignore the output**

Append to repo root `.gitignore`:

```
seed_preview.html
```

- [ ] **Step 5: Full gate, then commit**

```bash
git add maps/management/commands/seed_preview.py maps/tests/test_seed_preview.py ../.gitignore
git commit -m "feat: seed_preview command — validate + HTML map preview"
```

---

### Task 5: Frontend follow-through (demo hint + fixtures)

**Files:**
- Modify: `frontend/src/locales/en.json:86`
- Modify: `frontend/e2e/session-expiry.spec.ts:17`

**Interfaces:** none — string updates required by the persona rename.

- [ ] **Step 1: Update the demo hint**

In `frontend/src/locales/en.json` change:

```json
"auth.demoHint": "Try the demo: friend@demo.example / demo-pass-12345",
```

to:

```json
"auth.demoHint": "Try the demo: running.friend@demo.example / demo-pass-12345",
```

- [ ] **Step 2: Update the e2e fixture**

In `frontend/e2e/session-expiry.spec.ts` change:

```ts
const USER = { id: "u1", display_name: "A Friend", email: "friend@demo.example", reputation: 10 };
```

to:

```ts
const USER = { id: "u1", display_name: "A Running Friend", email: "running.friend@demo.example", reputation: 10 };
```

- [ ] **Step 3: Sweep for stragglers**

Run: `grep -rn "friend@demo.example\|A Friend" frontend/src frontend/e2e frontend/e2e-prod`
Expected: zero hits for the OLD email (`friend@demo.example` — note `running.friend@demo.example` contains it as a suffix, so check matches carefully); any `"A Friend"` display-name hits get the same rename.

- [ ] **Step 4: Frontend gate**

Run from `frontend/`: `npm run lint && npm run test -- --run && npm run build && npm run e2e`
Expected: all green (session-expiry spec passes with the renamed fixture)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/locales/en.json frontend/e2e/session-expiry.spec.ts
git commit -m "feat: demo-login hint follows the friend persona rename"
```

---

### Task 6: End-to-end verification (controller-level)

**Files:** none created — verification only.

- [ ] **Step 1: Full backend + frontend gates one more time** (both suites, all linters — see Global Constraints).
- [ ] **Step 2: Rebuild a local demo DB:** from `backend/`: `docker compose up -d db` (wait for `pg_isready`), `uv run python manage.py migrate`, `uv run python manage.py seed_demo --refresh` twice (second run must report a stable seed count — idempotency in anger).
- [ ] **Step 3: Generate and READ the preview:** `uv run python manage.py seed_preview` → open/Read `seed_preview.html` conceptually via a headless-Playwright screenshot (`npx playwright screenshot "file://$PWD/seed_preview.html" preview.png --viewport-size=1280,900` from `frontend/`, then Read the PNG). Verify: pins cluster downtown/North End/Chinatown, 5+ routes visible, polygons on the parks, the ⚠ showcase badge on Charles River loop's popup.
- [ ] **Step 4: In-app screenshot:** run backend (`uv run python manage.py runserver`) + `npm run dev`, screenshot the map as Guest and as a logged-in persona via the existing headless-Playwright technique; verify the map reads as lived-in and persona switching visibly re-filters.
- [ ] **Step 5: Commit any fixes; the branch is then ready for PR** (PR body must carry the repo's required sections: `## Summary`, `## Provenance`, `## Reasoning`, `## Testing`, `## Risk & rollback`).
