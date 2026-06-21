from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.contrib.gis.geos import LineString, Point, Polygon

from core.models import Group, Membership, Tenant, User
from maps.models import Map, Note, Section

DEMO_PASSWORD = "demo-pass-12345"  # public demo credential, surfaced in the UI hint


def build_boston_demo() -> dict:
    tenant, _ = Tenant.objects.get_or_create(slug="boston", defaults={"name": "Boston Demo"})

    _hashed = make_password(DEMO_PASSWORD)
    owner, _ = User.objects.get_or_create(
        display_name="You (owner)",
        defaults={"reputation": 100, "email": "owner@demo.example", "password": _hashed},
    )
    friend, _ = User.objects.get_or_create(
        display_name="A Friend",
        defaults={"reputation": 10, "email": "friend@demo.example", "password": _hashed},
    )
    runner, _ = User.objects.get_or_create(
        display_name="Run-club Member",
        defaults={"reputation": 30, "email": "runner@demo.example", "password": _hashed},
    )
    local, _ = User.objects.get_or_create(
        display_name="Reputable Local",
        defaults={"reputation": 60, "email": "local@demo.example", "password": _hashed},
    )

    for user, role in [
        (owner, Membership.Role.OWNER),
        (friend, Membership.Role.CONTRIBUTOR),
        (runner, Membership.Role.CONTRIBUTOR),
        (local, Membership.Role.CONTRIBUTOR),
    ]:
        Membership.objects.get_or_create(user=user, tenant=tenant, defaults={"role": role})
    club, _ = Group.objects.get_or_create(tenant=tenant, name="Running club")
    club.members.set([runner])

    the_map, _ = Map.objects.get_or_create(
        tenant=tenant,
        name="Greater Boston",
        defaults={"center": Point(-71.0589, 42.3601), "default_zoom": 12},
    )

    note, created = Note.objects.get_or_create(
        tenant=tenant,
        map=the_map,
        author=owner,
        title="Castle Island — Pleasure Bay Loop",
        defaults={"point": Point(-71.0136, 42.3380), "is_seed": True},
    )
    if created:
        Section.objects.bulk_create(
            [
                Section(
                    note=note,
                    order=0,
                    rule_type=Section.RuleType.PUBLIC,
                    content="Flat, scenic ~2.5-mi loop around the bay. Great easy day.",
                ),
                Section(
                    note=note,
                    order=1,
                    rule_type=Section.RuleType.AUDIENCE,
                    rule_params={"user_ids": [str(friend.id)]},
                    content="Parking fills by 9am — use the far lot by the fort.",
                ),
                Section(
                    note=note,
                    order=2,
                    rule_type=Section.RuleType.AUDIENCE,
                    teaser=True,
                    rule_params={"group_ids": [str(club.id)]},
                    content=(
                        "Water fountain + restrooms by the fort; Sullivan's sells water & Gatorade."
                    ),
                ),
                Section(
                    note=note,
                    order=3,
                    rule_type=Section.RuleType.ATTRIBUTE_GATE,
                    rule_params={"attribute": "reputation", "threshold": 50},
                    content="Trusted-local tip: the back stretch ices over first in winter.",
                ),
                Section(
                    note=note,
                    order=4,
                    rule_type=Section.RuleType.PRIVATE,
                    content="Reminder: right knee twinges on the back stretch — ease off.",
                ),
            ]
        )

    area_note, area_created = Note.objects.get_or_create(
        tenant=tenant,
        map=the_map,
        author=local,
        title="Boston Public Garden",
        defaults={
            "is_seed": True,
            "area": Polygon(
                (
                    (-71.0723, 42.3539),
                    (-71.0699, 42.3551),
                    (-71.0685, 42.3537),
                    (-71.0709, 42.3525),
                    (-71.0723, 42.3539),
                )
            ),
        },
    )
    if area_created:
        Section.objects.create(
            note=area_note,
            order=0,
            rule_type=Section.RuleType.PUBLIC,
            content="Swan boats + the willows. Calm loop, good for an easy shakeout.",
        )

    route_note, route_created = Note.objects.get_or_create(
        tenant=tenant,
        map=the_map,
        author=runner,
        title="Charles Esplanade out-and-back",
        defaults={
            "is_seed": True,
            "path": LineString(
                (-71.0735, 42.3562),
                (-71.0820, 42.3575),
                (-71.0905, 42.3585),
                (-71.0980, 42.3590),
            ),
        },
    )
    if route_created:
        Section.objects.create(
            note=route_note,
            order=0,
            rule_type=Section.RuleType.PUBLIC,
            content="Flat riverside path. ~2km each way; water fountain at the footbridge.",
        )

    return {
        "tenant": tenant,
        "map": the_map,
        "owner": owner,
        "friend": friend,
        "runner": runner,
        "local": local,
        "club": club,
        "note": note,
        "area_note": area_note,
        "route_note": route_note,
    }
