from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ninja import Schema
from pydantic import field_validator, model_validator

from maps.models import Section


class SectionOut(Schema):
    id: UUID
    order: int
    visibility: str  # "visible" | "teaser"
    content: str | None  # null when teaser (redacted)
    rule_type: str
    rule_label: str
    teaser_text: str | None  # the custom hook, only for locked (teaser) sections


class ShapeOut(Schema):
    kind: str  # "polygon" | "line"
    # [lng, lat] pairs: a polygon's outer ring, or a line's path
    coordinates: list[tuple[float, float]]


class ShapeIn(Schema):
    kind: str  # "polygon" | "line"
    coordinates: list[tuple[float, float]]  # [lng, lat] pairs

    @field_validator("kind")
    @classmethod
    def _kind_valid(cls, v: str) -> str:
        if v not in ("polygon", "line"):
            raise ValueError(f"invalid shape kind {v!r}")
        return v

    @model_validator(mode="after")
    def _enough_coordinates(self) -> ShapeIn:
        if self.kind == "polygon" and len(self.coordinates) < 3:
            raise ValueError("a polygon needs at least 3 coordinates")
        if self.kind == "line" and len(self.coordinates) < 2:
            raise ValueError("a line needs at least 2 coordinates")
        return self


class AppendOut(Schema):
    id: UUID
    author_id: UUID
    author_name: str
    title: str
    sections: list[SectionOut]
    editable: bool


class NoteOut(Schema):
    id: UUID
    author_id: UUID
    title: str
    lng: float | None
    lat: float | None
    sections: list[SectionOut]
    appends: list[AppendOut] = []
    editable: bool
    shape: ShapeOut | None = None


class SectionIn(Schema):
    order: int = 0
    content: str
    rule_type: str
    rule_params: dict = {}
    teaser: bool = False
    teaser_text: str = ""

    @field_validator("rule_type")
    @classmethod
    def _rule_type_is_valid(cls, v: str) -> str:
        if v not in Section.RuleType.values:
            raise ValueError(f"invalid rule_type {v!r}")
        return v

    @field_validator("content")
    @classmethod
    def _content_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content is required")
        return v

    @model_validator(mode="after")
    def _rule_params_match_type(self) -> SectionIn:
        if self.rule_type == Section.RuleType.AUDIENCE:
            user_ids = self.rule_params.get("user_ids", [])
            group_ids = self.rule_params.get("group_ids", [])
            if not user_ids and not group_ids:
                raise ValueError("audience requires at least one user or group")
            for raw in [*user_ids, *group_ids]:
                UUID(str(raw))  # ValueError if not a UUID
        elif self.rule_type == Section.RuleType.ATTRIBUTE_GATE:
            if "attribute" not in self.rule_params:
                raise ValueError("attribute_gate requires 'attribute'")
            if "threshold" not in self.rule_params:
                raise ValueError("attribute_gate requires 'threshold'")
            float(self.rule_params["threshold"])  # ValueError if non-numeric
        return self


class NoteIn(Schema):
    title: str = ""
    lng: float | None = None
    lat: float | None = None
    shape: ShapeIn | None = None
    sections: list[SectionIn] = []

    @field_validator("title")
    @classmethod
    def _title_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title is required")
        return v

    @field_validator("sections")
    @classmethod
    def _at_least_one_section(cls, v: list[SectionIn]) -> list[SectionIn]:
        if not v:
            raise ValueError("a note needs at least one section")
        return v

    @model_validator(mode="after")
    def _exactly_one_anchor(self) -> NoteIn:
        has_point = self.lng is not None and self.lat is not None
        has_shape = self.shape is not None
        if has_point == has_shape:  # both, or neither
            raise ValueError("provide exactly one anchor: lng+lat OR shape")
        return self


class AppendIn(Schema):
    title: str = ""
    sections: list[SectionIn] = []

    @field_validator("sections")
    @classmethod
    def _at_least_one_section(cls, v: list[SectionIn]) -> list[SectionIn]:
        if not v:
            raise ValueError("an append needs at least one section")
        return v


class SectionEditOut(Schema):
    order: int
    content: str
    rule_type: str
    rule_params: dict
    teaser: bool
    teaser_text: str


class NoteEditOut(Schema):
    id: UUID
    title: str
    lng: float | None
    lat: float | None
    version: int
    sections: list[SectionEditOut]


class NoteUpdateIn(NoteIn):
    version: int


class AppendUpdateIn(AppendIn):
    version: int


class NoteUpdated(Schema):
    id: UUID
    version: int


class NoteCreated(Schema):
    id: UUID


class MapOut(Schema):
    id: UUID
    name: str
    lng: float
    lat: float
    zoom: int


class ViewerOut(Schema):
    id: UUID
    display_name: str
    reputation: int


class GroupOut(Schema):
    id: UUID
    name: str


class ModItemOut(Schema):
    id: UUID
    kind: str  # "note" | "append"
    title: str
    snippet: str
    author_name: str
    session_key: str  # FULL key (token-gated, safe to expose to the moderator); UI truncates
    created_ip: str | None
    created_at: datetime
    updated_at: datetime
    version: int
    map_name: str


class ModDeleteIn(Schema):
    ids: list[UUID] | None = None
    session_key: str | None = None
    created_ip: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self):
        provided = [self.ids is not None, bool(self.session_key), bool(self.created_ip)]
        if sum(provided) != 1:
            raise ValueError("Provide exactly one of: ids, session_key, created_ip.")
        return self


class ModDeleteOut(Schema):
    deleted: int
