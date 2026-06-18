from __future__ import annotations

from uuid import UUID

from django.contrib.gis.geos import Point
from django.db import transaction
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from core.models import Group, Membership, User
from core.visibility import Visibility
from core.visibility.resolve import resolve_viewer
from maps.models import Map, Note, Section
from maps.schemas import (
    AppendOut,
    GroupOut,
    MapOut,
    NoteCreated,
    NoteEditOut,
    NoteIn,
    NoteOut,
    NoteUpdated,
    NoteUpdateIn,
    SectionEditOut,
    SectionOut,
    ViewerOut,
)
from maps.visibility import section_label, section_visibility

router = Router()


@router.get("/maps", response=list[MapOut])
def list_maps(request):
    return [
        MapOut(id=m.id, name=m.name, lng=m.center.x, lat=m.center.y, zoom=m.default_zoom)
        for m in Map.objects.all()
    ]


@router.get("/maps/{map_id}/viewers", response=list[ViewerOut])
def list_viewers(request, map_id: UUID):
    # Demo scaffolding: the seeded members of this map's tenant, for the preview-as switcher.
    # FIXME(A5): replaced by real authenticated identity.
    the_map = get_object_or_404(Map, id=map_id)
    user_ids = Membership.objects.filter(tenant=the_map.tenant).values_list("user_id", flat=True)
    return [
        ViewerOut(id=u.id, display_name=u.display_name, reputation=u.reputation)
        for u in User.objects.filter(id__in=user_ids).order_by("reputation")
    ]


@router.get("/maps/{map_id}/groups", response=list[GroupOut])
def list_groups(request, map_id: UUID):
    the_map = get_object_or_404(Map, id=map_id)
    return [GroupOut(id=g.id, name=g.name) for g in Group.objects.filter(tenant=the_map.tenant)]


def _visible_sections(note: Note, viewer) -> list[SectionOut]:
    out: list[SectionOut] = []
    for section in note.sections.all():
        vis = section_visibility(section, viewer, owner_id=note.author_id)
        if vis is Visibility.HIDDEN:
            continue
        out.append(
            SectionOut(
                id=section.id,
                order=section.order,
                visibility=vis.value,
                content=section.content if vis is Visibility.VISIBLE else None,
                rule_type=section.rule_type,
                rule_label=section_label(section),
                teaser_text=(section.teaser_text or None) if vis is Visibility.TEASER else None,
            )
        )
    return out


@router.get("/maps/{map_id}/notes", response=list[NoteOut])
def list_notes(request, map_id: UUID, preview_as: UUID | None = None):
    the_map = get_object_or_404(Map, id=map_id)
    viewer = resolve_viewer(preview_as, the_map.tenant)
    top_level = (
        the_map.notes.filter(parent__isnull=True)
        .select_related("author")
        .prefetch_related("sections", "appends__author", "appends__sections")
    )
    out: list[NoteOut] = []
    for note in top_level:
        visible = _visible_sections(note, viewer)
        if not visible:
            continue
        appends: list[AppendOut] = []
        for ap in note.appends.all():
            ap_sections = _visible_sections(ap, viewer)
            if not ap_sections:
                continue
            appends.append(
                AppendOut(
                    id=ap.id,
                    author_id=ap.author_id,
                    author_name=ap.author.display_name,
                    title=ap.title,
                    sections=ap_sections,
                )
            )
        out.append(
            NoteOut(
                id=note.id,
                author_id=note.author_id,
                title=note.title,
                lng=note.point.x if note.point else None,
                lat=note.point.y if note.point else None,
                sections=visible,
                appends=appends,
            )
        )
    return out


@router.post("/maps/{map_id}/notes", response={201: NoteCreated})
def create_note(request, map_id: UUID, payload: NoteIn, preview_as: UUID | None = None):
    the_map = get_object_or_404(Map, id=map_id)
    if preview_as is None:
        raise HttpError(403, "Sign in (preview-as) to add notes.")
    author = get_object_or_404(User, id=preview_as)
    note = Note.objects.create(
        tenant=the_map.tenant,
        map=the_map,
        author=author,
        title=payload.title,
        point=Point(payload.lng, payload.lat),
    )
    for s in payload.sections:
        Section.objects.create(
            note=note,
            order=s.order,
            content=s.content,
            rule_type=s.rule_type,
            rule_params=s.rule_params,
            teaser=s.teaser,
            teaser_text=s.teaser_text,
        )
    return 201, {"id": note.id}


@router.get("/notes/{note_id}/edit", response=NoteEditOut)
def note_for_edit(request, note_id: UUID, preview_as: UUID | None = None):
    note = get_object_or_404(Note, id=note_id)
    if preview_as is None or note.author_id != preview_as:
        raise HttpError(403, "You can only edit your own notes.")
    return NoteEditOut(
        id=note.id,
        title=note.title,
        lng=note.point.x if note.point else None,
        lat=note.point.y if note.point else None,
        version=note.version,
        sections=[
            SectionEditOut(
                order=s.order,
                content=s.content,
                rule_type=s.rule_type,
                rule_params=s.rule_params,
                teaser=s.teaser,
                teaser_text=s.teaser_text,
            )
            for s in note.sections.all()
        ],
    )


@router.delete("/notes/{note_id}", response={204: None})
def delete_note(request, note_id: UUID, preview_as: UUID | None = None):
    note = get_object_or_404(Note, id=note_id)
    if preview_as is None or note.author_id != preview_as:
        raise HttpError(403, "You can only delete your own notes.")
    note.soft_delete()
    return 204, None


@router.put("/notes/{note_id}", response={200: NoteUpdated})
def update_note(request, note_id: UUID, payload: NoteUpdateIn, preview_as: UUID | None = None):
    note = get_object_or_404(Note, id=note_id)
    if preview_as is None or note.author_id != preview_as:
        raise HttpError(403, "You can only edit your own notes.")
    if note.version != payload.version:
        raise HttpError(409, "This note changed elsewhere — reload to edit.")
    with transaction.atomic():
        note.title = payload.title
        note.point = Point(payload.lng, payload.lat)
        note.save()  # BaseModel.save() bumps version
        # Replace sections wholesale. NB: QuerySet.delete() HARD-deletes (Section is
        # soft-deletable, but .delete() issues a SQL DELETE) — intentional for now;
        # the future revision-history slice will need to soft-delete/snapshot instead.
        note.sections.all().delete()
        for s in payload.sections:
            Section.objects.create(
                note=note,
                order=s.order,
                content=s.content,
                rule_type=s.rule_type,
                rule_params=s.rule_params,
                teaser=s.teaser,
                teaser_text=s.teaser_text,
            )
    return 200, {"id": note.id, "version": note.version}
