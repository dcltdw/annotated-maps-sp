from __future__ import annotations

from uuid import UUID

from django.shortcuts import get_object_or_404
from ninja import Router

from core.visibility import Visibility
from core.visibility.resolve import resolve_viewer
from maps.models import Map
from maps.schemas import NoteOut, SectionOut
from maps.visibility import section_visibility

router = Router()


@router.get("/maps/{map_id}/notes", response=list[NoteOut])
def list_notes(request, map_id: UUID, preview_as: UUID | None = None):
    the_map = get_object_or_404(Map, id=map_id)
    viewer = resolve_viewer(preview_as, the_map.tenant)
    out: list[NoteOut] = []
    for note in the_map.notes.select_related("author").prefetch_related("sections"):
        visible_sections: list[SectionOut] = []
        for section in note.sections.all():
            vis = section_visibility(section, viewer, owner_id=note.author_id)
            if vis is Visibility.HIDDEN:
                continue
            visible_sections.append(
                SectionOut(
                    id=section.id,
                    order=section.order,
                    visibility=vis.value,
                    content=section.content if vis is Visibility.VISIBLE else None,
                )
            )
        if not visible_sections:
            continue
        out.append(
            NoteOut(
                id=note.id,
                title=note.title,
                lng=note.point.x if note.point else None,
                lat=note.point.y if note.point else None,
                sections=visible_sections,
            )
        )
    return out
