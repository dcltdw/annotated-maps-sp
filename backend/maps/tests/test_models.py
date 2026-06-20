import pytest
from django.contrib.gis.geos import Point

from core.models import Tenant, User
from maps.models import Map, Note, Section


@pytest.mark.django_db
def test_note_with_point_and_ordered_sections():
    t = Tenant.objects.create(name="Boston", slug="boston")
    author = User.objects.create(display_name="Owner")
    m = Map.objects.create(tenant=t, name="Greater Boston", center=Point(-71.06, 42.36))
    note = Note.objects.create(
        tenant=t, map=m, author=author, title="Castle Island", point=Point(-71.013, 42.338)
    )
    Section.objects.create(note=note, order=1, content="b", rule_type=Section.RuleType.PRIVATE)
    Section.objects.create(note=note, order=0, content="a", rule_type=Section.RuleType.PUBLIC)

    assert [s.content for s in note.sections.all()] == ["a", "b"]  # ordered by `order`
    assert note.point is not None
    assert note.point.x == pytest.approx(-71.013)


@pytest.mark.django_db
def test_note_sandbox_fields_default_to_ephemeral():
    t = Tenant.objects.create(name="T", slug="t")
    u = User.objects.create(display_name="U")
    m = Map.objects.create(tenant=t, name="M", center=Point(0, 0))
    n = Note.objects.create(tenant=t, map=m, author=u, title="x", point=Point(0, 0))
    assert n.is_seed is False  # safe default: nothing is accidentally permanent
    assert n.session_key == ""
    assert n.created_ip is None


@pytest.mark.django_db
def test_note_can_hold_a_polygon_or_a_line(db):
    from django.contrib.gis.geos import LineString, Polygon

    t = Tenant.objects.create(name="T", slug="t")
    u = User.objects.create(display_name="U")
    m = Map.objects.create(tenant=t, name="M", center=Point(0, 0))
    area = Note.objects.create(
        tenant=t,
        map=m,
        author=u,
        title="area",
        area=Polygon(((0, 0), (0, 1), (1, 1), (1, 0), (0, 0))),
    )
    path = Note.objects.create(
        tenant=t, map=m, author=u, title="path", path=LineString((0, 0), (1, 1), (2, 0))
    )
    area.refresh_from_db()
    path.refresh_from_db()
    assert area.area is not None and area.point is None and area.path is None
    assert path.path is not None and path.point is None and path.area is None


def test_top_level_note_requires_exactly_one_anchor(db):
    import pytest
    from django.contrib.gis.geos import Point, Polygon
    from django.db import IntegrityError

    from core.models import Tenant, User
    from maps.models import Map, Note

    t = Tenant.objects.create(name="T2", slug="t2")
    u = User.objects.create(display_name="U")
    m = Map.objects.create(tenant=t, name="M", center=Point(0, 0))
    with pytest.raises(IntegrityError):
        Note.objects.create(
            tenant=t,
            map=m,
            author=u,
            title="bad",
            point=Point(0, 0),
            area=Polygon(((0, 0), (0, 1), (1, 1), (0, 0))),
        )


def test_append_may_have_no_anchor(db):
    from django.contrib.gis.geos import Point

    from core.models import Tenant, User
    from maps.models import Map, Note

    t = Tenant.objects.create(name="T3", slug="t3")
    u = User.objects.create(display_name="U")
    m = Map.objects.create(tenant=t, name="M", center=Point(0, 0))
    parent = Note.objects.create(tenant=t, map=m, author=u, title="p", point=Point(0, 0))
    ap = Note.objects.create(tenant=t, map=m, author=u, parent=parent, title="ap")
    assert ap.point is None and ap.area is None and ap.path is None
