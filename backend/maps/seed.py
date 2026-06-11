from __future__ import annotations

from django.contrib.gis.geos import Point

from core.models import Group, Membership, Tenant, User
from maps.models import Map, Note, Section


def build_boston_demo() -> dict:
    tenant, _ = Tenant.objects.get_or_create(slug="boston", defaults={"name": "Boston Demo"})

    owner, _ = User.objects.get_or_create(display_name="You (owner)", defaults={"reputation": 100})
    friend, _ = User.objects.get_or_create(display_name="A Friend", defaults={"reputation": 10})
    runner, _ = User.objects.get_or_create(
        display_name="Run-club Member", defaults={"reputation": 30}
    )
    local, _ = User.objects.get_or_create(
        display_name="Reputable Local", defaults={"reputation": 60}
    )

    Membership.objects.get_or_create(
        user=owner, tenant=tenant, defaults={"role": Membership.Role.OWNER}
    )
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
        defaults={"point": Point(-71.0136, 42.3380)},
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

    return {
        "tenant": tenant,
        "map": the_map,
        "owner": owner,
        "friend": friend,
        "runner": runner,
        "local": local,
        "club": club,
        "note": note,
    }
