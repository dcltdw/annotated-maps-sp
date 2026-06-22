import pytest
from django.contrib.gis.geos import Point

from core.models import Tenant, User
from maps.models import Map, Note, Section


def client_as(user):
    """A Django test Client that authenticates as `user` via an A5.1a bearer token —
    every request carries `Authorization: Bearer <token>`. Use this for write-path tests
    (the authenticated identity owns content by author id)."""
    from django.test import Client, RequestFactory

    from core.auth import create_session

    token = create_session(user, RequestFactory().post("/"))
    return Client(HTTP_AUTHORIZATION=f"Bearer {token}")


@pytest.fixture
def world(db):
    """A minimal demo world: one tenant/map, two personas, and one SEED note."""
    tenant = Tenant.objects.create(name="Demo", slug="demo")
    alice = User.objects.create(display_name="Alice", reputation=50)
    bob = User.objects.create(display_name="Bob", reputation=10)
    the_map = Map.objects.create(tenant=tenant, name="Demo", center=Point(-71.06, 42.36))
    seed = Note.objects.create(
        tenant=tenant,
        map=the_map,
        author=alice,
        title="Seed",
        point=Point(-71.0, 42.3),
        is_seed=True,
    )
    Section.objects.create(note=seed, order=0, content="public", rule_type=Section.RuleType.PUBLIC)
    return {"tenant": tenant, "map": the_map, "alice": alice, "bob": bob, "seed": seed}
