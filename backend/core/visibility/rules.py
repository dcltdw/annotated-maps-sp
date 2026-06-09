from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from core.visibility.viewer import Viewer


class VisibilityRule:
    """A rule answers a single question: does it grant this viewer access?

    Owner-sees-all is handled by the engine, not by individual rules.
    """

    def grants(self, viewer: Viewer) -> bool:
        raise NotImplementedError


@dataclass(frozen=True)
class Public(VisibilityRule):
    def grants(self, viewer: Viewer) -> bool:
        return True


@dataclass(frozen=True)
class Private(VisibilityRule):
    def grants(self, viewer: Viewer) -> bool:
        return False


@dataclass(frozen=True)
class Audience(VisibilityRule):
    """Visible to specific users and/or members of specific groups."""

    user_ids: frozenset[UUID] = frozenset()
    group_ids: frozenset[UUID] = frozenset()

    def grants(self, viewer: Viewer) -> bool:
        if viewer.user_id is not None and viewer.user_id in self.user_ids:
            return True
        return bool(self.group_ids & viewer.group_ids)


@dataclass(frozen=True)
class AttributeGate(VisibilityRule):
    """Visible when the viewer's attribute meets a numeric threshold
    (e.g. reputation >= 50). A missing attribute (guest) never meets it.
    """

    attribute: str
    threshold: float

    def grants(self, viewer: Viewer) -> bool:
        value = viewer.attributes.get(self.attribute)
        return value is not None and value >= self.threshold
