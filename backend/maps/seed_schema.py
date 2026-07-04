"""Schema + lint for backend/maps/seed_data.geojson.

Single validation implementation shared by the seed loader, the CI tests,
and the seed_preview command. See docs/superpowers/specs/
2026-07-04-richer-seed-data-design.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

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
    def _bounds(self) -> PointGeom:
        _check_bounds([self.coordinates])
        return self


class LineGeom(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["LineString"]
    coordinates: list[LngLat] = Field(min_length=2)

    @model_validator(mode="after")
    def _bounds(self) -> LineGeom:
        _check_bounds(self.coordinates)
        return self


class PolygonGeom(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["Polygon"]
    coordinates: list[list[LngLat]] = Field(min_length=1, max_length=1)  # exterior ring only

    @model_validator(mode="after")
    def _ring(self) -> PolygonGeom:
        ring = self.coordinates[0]
        if len(ring) < 4:
            raise ValueError("polygon ring needs >= 4 points")
        if ring[0] != ring[-1]:
            raise ValueError("polygon ring is not closed (first != last)")
        _check_bounds(ring)
        return self


Geometry = Annotated[PointGeom | LineGeom | PolygonGeom, Field(discriminator="type")]


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
    def _rule_shape(self) -> SeedSection:
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
    def _append_shape(self) -> SeedFeature:
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
    def _cross_feature(self) -> SeedFile:
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
