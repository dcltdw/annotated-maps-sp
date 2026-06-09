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
