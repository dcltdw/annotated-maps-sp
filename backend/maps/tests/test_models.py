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
