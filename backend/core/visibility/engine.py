from __future__ import annotations

from enum import Enum
from uuid import UUID

from core.visibility.rules import VisibilityRule
from core.visibility.viewer import Viewer


class Visibility(Enum):
    VISIBLE = "visible"
    TEASER = "teaser"
    HIDDEN = "hidden"


def can_view(
    viewer: Viewer,
    *,
    owner_id: UUID,
    rule: VisibilityRule,
    teaser: bool = False,
) -> Visibility:
    """Resolve a viewer's access to one section: owner-sees-all, then the rule,
    then teaser-vs-hidden for the denied case. Pure and deterministic.
    """
    if viewer.user_id is not None and viewer.user_id == owner_id:
        return Visibility.VISIBLE
    if rule.grants(viewer):
        return Visibility.VISIBLE
    return Visibility.TEASER if teaser else Visibility.HIDDEN
