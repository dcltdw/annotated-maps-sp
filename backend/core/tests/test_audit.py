import pytest

from core.audit import record_event
from core.models import AuditEvent, Tenant


@pytest.mark.django_db
def test_record_event_persists_an_audit_row():
    tenant = Tenant.objects.create(name="A", slug="a")
    record_event("tenant.created", tenant=tenant, actor_id=None, target=tenant, note="seed")
    e = AuditEvent.all_objects.get()
    assert e.action == "tenant.created"
    assert e.tenant_id == tenant.id
    assert e.target_type == "Tenant"
    assert str(e.target_id) == str(tenant.id)
    assert e.metadata == {"note": "seed"}
