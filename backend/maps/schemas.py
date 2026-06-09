from __future__ import annotations

from uuid import UUID

from ninja import Schema


class SectionOut(Schema):
    id: UUID
    order: int
    visibility: str  # "visible" | "teaser"
    content: str | None  # null when teaser (redacted)


class NoteOut(Schema):
    id: UUID
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


class NoteIn(Schema):
    title: str = ""
    lng: float
    lat: float
    sections: list[SectionIn] = []


class NoteCreated(Schema):
    id: UUID
