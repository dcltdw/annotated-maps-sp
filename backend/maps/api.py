from __future__ import annotations

from uuid import UUID

from django.conf import settings
from django.contrib.gis.geos import LineString, Point, Polygon
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Status
from ninja.errors import HttpError

from core.models import Group, Membership, User
from core.visibility import Visibility
from core.visibility.resolve import resolve_viewer
from maps.models import Map, Note, Section
from maps.sandbox import authorize_write, enforce_create_limits, is_editable
from maps.schemas import (
    AppendIn,
    AppendOut,
    AppendUpdateIn,
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
    ShapeOut,
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


def _anchor_fields(payload: NoteIn) -> dict:
    """Turn a NoteIn's anchor into a {point, area, path} dict (one set, two None).
    Raises HttpError(422) for invalid geometry. NoteIn's validator already guarantees
    exactly one anchor, so exactly one branch applies."""
    if payload.shape is not None:
        if payload.shape.kind == "polygon":
            ring = [(x, y) for x, y in payload.shape.coordinates]
            if ring[0] != ring[-1]:
                ring.append(ring[0])  # GEOS needs a closed ring
            poly = Polygon(ring)
            if not poly.valid:
                raise HttpError(422, "Invalid polygon (edges cross?).")
            return {"point": None, "area": poly, "path": None}
        return {"point": None, "area": None, "path": LineString(payload.shape.coordinates)}
    return {"point": Point(payload.lng, payload.lat), "area": None, "path": None}


def _note_shape(note: Note) -> ShapeOut | None:
    """Serialize a note's area/path anchor as a [lng,lat] shape (None for point notes)."""
    if note.area is not None:
        ring = [(x, y) for x, y in note.area.exterior_ring.coords]
        return ShapeOut(kind="polygon", coordinates=ring)
    if note.path is not None:
        return ShapeOut(kind="line", coordinates=[(x, y) for x, y in note.path.coords])
    return None


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
                    editable=is_editable(request, ap, preview_as),
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
                editable=is_editable(request, note, preview_as),
                shape=_note_shape(note),
            )
        )
    return out


@router.post("/maps/{map_id}/notes", response={201: NoteCreated})
def create_note(request, map_id: UUID, payload: NoteIn, preview_as: UUID | None = None):
    the_map = get_object_or_404(Map, id=map_id)
    if preview_as is None:
        raise HttpError(403, "Sign in (preview-as) to add notes.")
    author = get_object_or_404(User, id=preview_as)
    session_key, created_ip = "", None
    if settings.SANDBOX_MODE:
        session_key, created_ip = enforce_create_limits(request, is_append=False)
    anchor = _anchor_fields(payload)  # may raise 422 on invalid geometry
    note = Note.objects.create(
        tenant=the_map.tenant,
        map=the_map,
        author=author,
        title=payload.title,
        session_key=session_key,
        created_ip=created_ip,
        **anchor,
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
    return Status(201, {"id": note.id})


@router.get("/notes/{note_id}/edit", response=NoteEditOut)
def note_for_edit(request, note_id: UUID, preview_as: UUID | None = None):
    note = get_object_or_404(Note, id=note_id)
    authorize_write(request, note, preview_as, noun="note")
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
    authorize_write(request, note, preview_as, noun="note")
    note.soft_delete()
    return Status(204, None)


@router.put("/notes/{note_id}", response={200: NoteUpdated})
def update_note(request, note_id: UUID, payload: NoteUpdateIn, preview_as: UUID | None = None):
    note = get_object_or_404(Note, id=note_id)
    authorize_write(request, note, preview_as, noun="note")
    with transaction.atomic():
        # Atomically claim the version: exactly one of two racing PUTs can match
        # WHERE version=expected; the loser updates 0 rows -> 409. (.update() bypasses
        # BaseModel.save(), so bump version + updated_at explicitly.)
        claimed = Note.objects.filter(id=note.id, version=payload.version).update(
            version=F("version") + 1,
            updated_at=timezone.now(),
            title=payload.title,
            point=Point(payload.lng, payload.lat),
        )
        if not claimed:
            raise HttpError(409, "This note changed elsewhere — reload to edit.")
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
    note.refresh_from_db()  # in-memory note is stale after the raw UPDATE
    return Status(200, {"id": note.id, "version": note.version})


@router.put("/appends/{append_id}", response={200: NoteUpdated})
def update_append(
    request, append_id: UUID, payload: AppendUpdateIn, preview_as: UUID | None = None
):
    append = get_object_or_404(Note, id=append_id)
    authorize_write(request, append, preview_as, noun="append")
    if append.parent_id is None:
        # Refuse to edit a top-level note through the append endpoint — that would
        # bypass the note write schema (e.g. its required title). Use PUT /notes/{id}.
        raise HttpError(400, "Not an append.")
    with transaction.atomic():
        # Atomically claim the version (see update_note). Appends have no point.
        claimed = Note.objects.filter(id=append.id, version=payload.version).update(
            version=F("version") + 1,
            updated_at=timezone.now(),
            title=payload.title,
        )
        if not claimed:
            raise HttpError(409, "This append changed elsewhere — reload to edit.")
        append.sections.all().delete()  # hard replace (see update_note for the rationale)
        for s in payload.sections:
            Section.objects.create(
                note=append,
                order=s.order,
                content=s.content,
                rule_type=s.rule_type,
                rule_params=s.rule_params,
                teaser=s.teaser,
                teaser_text=s.teaser_text,
            )
    append.refresh_from_db()  # in-memory append is stale after the raw UPDATE
    return Status(200, {"id": append.id, "version": append.version})


@router.post("/notes/{parent_id}/appends", response={201: NoteCreated})
def create_append(request, parent_id: UUID, payload: AppendIn, preview_as: UUID | None = None):
    parent = get_object_or_404(Note, id=parent_id)
    if preview_as is None:
        raise HttpError(403, "Sign in (preview-as) to append.")
    if parent.parent_id is not None:
        raise HttpError(400, "You can only append to a top-level note.")
    author = get_object_or_404(User, id=preview_as)
    session_key, created_ip = "", None
    if settings.SANDBOX_MODE:
        session_key, created_ip = enforce_create_limits(request, is_append=True)
    append = Note.objects.create(
        tenant=parent.tenant,
        map=parent.map,
        author=author,
        parent=parent,
        title=payload.title,
        point=None,
        session_key=session_key,
        created_ip=created_ip,
    )
    for s in payload.sections:
        Section.objects.create(
            note=append,
            order=s.order,
            content=s.content,
            rule_type=s.rule_type,
            rule_params=s.rule_params,
            teaser=s.teaser,
            teaser_text=s.teaser_text,
        )
    return Status(201, {"id": append.id})
