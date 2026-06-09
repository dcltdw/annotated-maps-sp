from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class Viewer:
    """Who is looking. A guest is ``Viewer()`` (no user_id, no groups, no attributes)."""

    user_id: UUID | None = None
    group_ids: frozenset[UUID] = frozenset()
    attributes: Mapping[str, float] = field(default_factory=dict)

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None
