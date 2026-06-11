import pytest

from core.models import Group, Membership, Tenant, User


@pytest.mark.django_db
def test_user_has_display_name_and_reputation():
    u = User.objects.create(display_name="Dana", reputation=50)
    assert str(u) == "Dana"
    assert u.reputation == 50


@pytest.mark.django_db
def test_group_membership_and_roles():
    t = Tenant.objects.create(name="Boston", slug="boston")
    owner = User.objects.create(display_name="Owner")
    runner = User.objects.create(display_name="Runner")
    club = Group.objects.create(tenant=t, name="Running club")
    club.members.add(runner)
    Membership.objects.create(user=owner, tenant=t, role=Membership.Role.OWNER)

    assert runner.groups.filter(tenant=t).count() == 1
    assert owner.memberships.get(tenant=t).role == "owner"
