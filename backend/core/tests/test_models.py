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


@pytest.mark.django_db
def test_user_has_email_and_password_fields(db):
    from core.models import User

    u = User.objects.create(display_name="X", email="x@example.com", password="hashed")
    u.refresh_from_db()
    assert u.email == "x@example.com" and u.password == "hashed"


@pytest.mark.django_db
def test_email_is_unique_but_nullable(db):
    import pytest
    from django.db import IntegrityError

    from core.models import User

    User.objects.create(display_name="A")  # no email → allowed
    User.objects.create(display_name="B")  # second null email → allowed (Postgres)
    User.objects.create(display_name="C", email="dup@example.com")
    with pytest.raises(IntegrityError):
        User.objects.create(display_name="D", email="dup@example.com")


@pytest.mark.django_db
def test_authsession_links_to_user(db):
    from datetime import timedelta

    from django.utils import timezone

    from core.models import AuthSession, User

    u = User.objects.create(display_name="X")
    s = AuthSession.objects.create(
        user=u, token_hash="abc123", expires_at=timezone.now() + timedelta(days=14)
    )
    s.refresh_from_db()
    assert s.user_id == u.id and s.token_hash == "abc123"
