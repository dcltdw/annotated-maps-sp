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

    @field_validator("rule_type")
    @classmethod
    def _rule_type_is_valid(cls, v: str) -> str:
        if v not in Section.RuleType.values:
            raise ValueError(f"invalid rule_type {v!r}")
        return v

    @model_validator(mode="after")
    def _rule_params_match_type(self) -> SectionIn:
        if self.rule_type == Section.RuleType.AUDIENCE:
            for key in ("user_ids", "group_ids"):
                for raw in self.rule_params.get(key, []):
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
