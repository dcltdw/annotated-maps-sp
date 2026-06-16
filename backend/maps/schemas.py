from __future__ import annotations

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


class NoteOut(Schema):
    id: UUID
    author_id: UUID
    title: str
    lng: float | None
    lat: float | None
    sections: list[SectionOut]


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
    lng: float
    lat: float
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
