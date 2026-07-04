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
        assert props.parent is not None  # guaranteed by SeedFile.appends / schema validation
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
