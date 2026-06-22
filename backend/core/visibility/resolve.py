from __future__ import annotations

from uuid import UUID

from core.models import Tenant, User
from core.visibility import Viewer


def viewer_for(user: User, tenant: Tenant) -> Viewer:
    group_ids = frozenset(user.groups.filter(tenant=tenant).values_list("id", flat=True))
    return Viewer(
        user_id=user.id,
        group_ids=group_ids,
        attributes={"reputation": float(user.reputation)},
    )


def resolve_viewer(user_id: UUID | None, tenant: Tenant) -> Viewer:
    """Resolve the current viewer from a preview-as user id. None / unknown → guest.
    This is the auth seam: A5 replaces the user_id source with a real session.
    """
    # The caller passes a user id resolved by core.auth.resolve_identity: an authenticated
    # bearer user always wins, and preview_as is honored only for an anonymous visitor under
    # SANDBOX_MODE. So this is no longer raw impersonation — outside the sandbox an
    # unauthenticated caller resolves to None (guest) here.
    if user_id is None:
        return Viewer()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Viewer()
    return viewer_for(user, tenant)
