from __future__ import annotations

from typing import Any

from core.models import AuditEvent, BaseModel, Tenant


def record_event(
    action: str,
    *,
    tenant: Tenant | None = None,
    actor_id: Any = None,
    target: BaseModel | None = None,
    **metadata: Any,
) -> AuditEvent:
    return AuditEvent.all_objects.create(
        action=action,
        tenant=tenant,
        actor_id=actor_id,
        target_type=type(target).__name__ if target else "",
        target_id=target.id if target else None,
        metadata=metadata,
    )
