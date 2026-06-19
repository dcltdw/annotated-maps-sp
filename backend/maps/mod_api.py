"""Token-gated moderation API for the public sandbox. Guarded by a shared MOD_TOKEN
secret (X-Mod-Token header); inert when MOD_TOKEN is unset. Exposes session/IP — these
fields are NEVER returned by the public note API, only here."""

from __future__ import annotations

import hmac

from django.conf import settings
from ninja import Router
from ninja.errors import HttpError

from maps.models import Note
from maps.schemas import ModItemOut

router = Router()


def require_mod_token(request) -> None:
    """Reject unless the request carries the correct X-Mod-Token (constant-time).
    An empty MOD_TOKEN setting rejects everything, so the tooling is off by default."""
    expected = settings.MOD_TOKEN
    provided = request.headers.get("X-Mod-Token", "")
    if not expected or not hmac.compare_digest(provided, expected):
        raise HttpError(401, "Unauthorized.")


@router.get("/mod/recent", response=list[ModItemOut])
def mod_recent(request, limit: int = 50):
    require_mod_token(request)
    limit = max(1, min(limit, 200))
    notes = (
        Note.objects.filter(is_seed=False)
        .select_related("author", "map")
        .prefetch_related("sections")
        .order_by("-updated_at")[:limit]
    )
    out: list[ModItemOut] = []
    for n in notes:
        first = next(iter(n.sections.all()), None)
        out.append(
            ModItemOut(
                id=n.id,
                kind="append" if n.parent_id else "note",
                title=n.title,
                snippet=(first.content[:80] if first else ""),
                author_name=n.author.display_name,
                session_key=n.session_key,
                created_ip=n.created_ip,
                created_at=n.created_at,
                updated_at=n.updated_at,
                version=n.version,
                map_name=n.map.name,
            )
        )
    return out
