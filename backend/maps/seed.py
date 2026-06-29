from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.contrib.gis.geos import LineString, Point, Polygon

from core.models import Group, Membership, Tenant, User
from maps.models import Map, Note, Section

DEMO_PASSWORD = "demo-pass-12345"  # public demo credential, surfaced in the UI hint


def build_boston_demo() -> dict:
    tenant, _ = Tenant.objects.get_or_create(slug="boston", defaults={"name": "Boston Demo"})

    owner, _ = User.objects.get_or_create(
        display_name="You (owner)",
        defaults={
            "reputation": 100,
            "email": "owner@demo.example",
            "password": make_password(DEMO_PASSWORD),
        },
    )
    friend, _ = User.objects.get_or_create(
        display_name="A Friend",
        defaults={
            "reputation": 10,
            "email": "friend@demo.example",
            "password": make_password(DEMO_PASSWORD),
        },
    )
    runner, _ = User.objects.get_or_create(
        display_name="Run-club Member",
        defaults={
            "reputation": 30,
            "email": "runner@demo.example",
            "password": make_password(DEMO_PASSWORD),
        },
    )
    local, _ = User.objects.get_or_create(
        display_name="Reputable Local",
        defaults={
            "reputation": 60,
            "email": "local@demo.example",
            "password": make_password(DEMO_PASSWORD),
        },
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
        # A spread of visibility tiers so each persona sees different hover content
        # (mirrors the Castle Island pin). Authored by the Reputable Local.
        Section.objects.bulk_create(
            [
                Section(
                    note=area_note,
                    order=0,
                    rule_type=Section.RuleType.PUBLIC,
                    content="Swan boats + the willows. Calm loop, good for an easy shakeout.",
                ),
                Section(
                    note=area_note,
                    order=1,
                    rule_type=Section.RuleType.AUDIENCE,
                    rule_params={"user_ids": [str(friend.id)]},
                    content="Meet by the Make Way for Ducklings statues — easy landmark.",
                ),
                Section(
                    note=area_note,
                    order=2,
                    rule_type=Section.RuleType.AUDIENCE,
                    teaser=True,
                    rule_params={"group_ids": [str(club.id)]},
                    content="Club shakeout: two laps of the lagoon path, then out onto the Common.",
                ),
                Section(
                    note=area_note,
                    order=3,
                    rule_type=Section.RuleType.ATTRIBUTE_GATE,
                    rule_params={"attribute": "reputation", "threshold": 50},
                    content=(
                        "Local tip: the Arlington St gate opens earliest — quietest before 8am."
                    ),
                ),
                Section(
                    note=area_note,
                    order=4,
                    rule_type=Section.RuleType.PRIVATE,
                    content="Note to self: confirm the swan boats are running before recommending.",
                ),
            ]
        )

    route_note, route_created = Note.objects.get_or_create(
        tenant=tenant,
        map=the_map,
        author=runner,
        title="Charles River loop",
        defaults={
            "is_seed": True,
            # Closed loop along the Charles River basin: start at Memorial Drive &
            # Mass Ave (Cambridge), east along Memorial Drive, across the Longfellow
            # Bridge to Boston, back west along the Esplanade, closing over the Mass
            # Ave (Harvard) Bridge. First and last vertex coincide. (lng, lat)
            "path": LineString(
                (-71.0920, 42.3578),
                (-71.0880, 42.3596),
                (-71.0840, 42.3610),
                (-71.0805, 42.3627),
                (-71.0793, 42.3641),
                (-71.0745, 42.3628),
                (-71.0707, 42.3611),
                (-71.0745, 42.3573),
                (-71.0800, 42.3546),
                (-71.0858, 42.3525),
                (-71.0905, 42.3517),
                (-71.0913, 42.3548),
                (-71.0920, 42.3578),
            ),
        },
    )
    if route_created:
        # A spread of visibility tiers so each persona sees different hover content.
        # Authored by the Run-club Member.
        Section.objects.bulk_create(
            [
                Section(
                    note=route_note,
                    order=0,
                    rule_type=Section.RuleType.PUBLIC,
                    content=(
                        "Flat ~4.5 km loop: east along Memorial Drive, over the Longfellow "
                        "Bridge, back along the Esplanade, closing across the Mass Ave bridge. "
                        "Water fountains near both bridges."
                    ),
                ),
                Section(
                    note=route_note,
                    order=1,
                    rule_type=Section.RuleType.AUDIENCE,
                    rule_params={"user_ids": [str(friend.id)]},
                    content=(
                        "Start from the Mass Ave bridge so you finish with the Esplanade views."
                    ),
                ),
                Section(
                    note=route_note,
                    order=2,
                    rule_type=Section.RuleType.AUDIENCE,
                    teaser=True,
                    rule_params={"group_ids": [str(club.id)]},
                    content="Club tempo: pick it up between the bridges, float the bridge climbs.",
                ),
                Section(
                    note=route_note,
                    order=3,
                    rule_type=Section.RuleType.ATTRIBUTE_GATE,
                    rule_params={"attribute": "reputation", "threshold": 50},
                    content="Trusted tip: the Esplanade puddles near the lagoon after heavy rain.",
                ),
                Section(
                    note=route_note,
                    order=4,
                    rule_type=Section.RuleType.PRIVATE,
                    content=(
                        "Reminder: refill at the Longfellow fountain — "
                        "the Mass Ave one is often off."
                    ),
                ),
            ]
        )

    # Friends-only pin: its single top-level section is friend-audience, so the note
    # itself is hidden from everyone except the friend (and the owner, as author).
    # 9 Tyler St, Chinatown. The Friend persona adds their own take as an append.
    china_pearl, china_created = Note.objects.get_or_create(
        tenant=tenant,
        map=the_map,
        author=owner,
        title="China Pearl",
        defaults={"point": Point(-71.0600, 42.3514), "is_seed": True},
    )
    if china_created:
        Section.objects.create(
            note=china_pearl,
            order=0,
            rule_type=Section.RuleType.AUDIENCE,
            rule_params={"user_ids": [str(friend.id)]},
            content="Favorite dim sum place.",
        )
        friend_take = Note.objects.create(
            tenant=tenant,
            map=the_map,
            author=friend,
            parent=china_pearl,
            is_seed=True,
        )
        # Public within the (friends-only) pin, so the owner sees the friend's note too.
        Section.objects.create(
            note=friend_take,
            order=0,
            rule_type=Section.RuleType.PUBLIC,
            content="Best shumai in town!",
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
        "china_pearl": china_pearl,
    }
