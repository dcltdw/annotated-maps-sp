import pytest

from core.models import Group, Tenant, User
from core.visibility import Viewer
from core.visibility.resolve import resolve_viewer, viewer_for


@pytest.mark.django_db
def test_viewer_for_carries_groups_and_reputation():
    t = Tenant.objects.create(name="Boston", slug="boston")
    u = User.objects.create(display_name="Runner", reputation=80)
    club = Group.objects.create(tenant=t, name="Running club")
    club.members.add(u)

    v = viewer_for(u, t)
    assert v.user_id == u.id
    assert club.id in v.group_ids
    assert v.attributes["reputation"] == 80.0


@pytest.mark.django_db
def test_resolve_viewer_none_is_guest():
    assert resolve_viewer(None, Tenant.objects.create(name="B", slug="b")) == Viewer()
