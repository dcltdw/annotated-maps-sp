import pytest

from core.models import Tenant


@pytest.mark.django_db
def test_tenant_has_uuid_pk_and_timestamps():
    t = Tenant.objects.create(name="Boston Demo", slug="boston-demo")
    assert str(t.id)  # UUID renders
    assert t.created_at is not None and t.updated_at is not None


@pytest.mark.django_db
def test_version_increments_on_save():
    t = Tenant.objects.create(name="A", slug="a")
    assert t.version == 1
    t.name = "B"
    t.save()
    assert t.version == 2


@pytest.mark.django_db
def test_soft_delete_hides_from_default_manager():
    t = Tenant.objects.create(name="A", slug="a")
    t.soft_delete()
    assert Tenant.objects.filter(pk=t.pk).count() == 0
    assert Tenant.all_objects.filter(pk=t.pk).count() == 1
    assert t.deleted_at is not None


def test_default_manager_is_soft_delete():
    assert type(Tenant._default_manager).__name__ == "SoftDeleteManager"
    assert type(Tenant._base_manager).__name__ == "Manager"
