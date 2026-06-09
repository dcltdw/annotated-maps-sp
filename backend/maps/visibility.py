from __future__ import annotations

from uuid import UUID

from core.visibility import (
    AttributeGate,
    Audience,
    Private,
    Public,
    Viewer,
    Visibility,
    VisibilityRule,
    can_view,
)
from maps.models import Section


def rule_for(section: Section) -> VisibilityRule:
    params = section.rule_params or {}
    try:
        match section.rule_type:
            case Section.RuleType.PUBLIC:
                return Public()
            case Section.RuleType.PRIVATE:
                return Private()
            case Section.RuleType.AUDIENCE:
                return Audience(
                    user_ids=frozenset(UUID(u) for u in params.get("user_ids", [])),
                    group_ids=frozenset(UUID(g) for g in params.get("group_ids", [])),
                )
            case Section.RuleType.ATTRIBUTE_GATE:
                return AttributeGate(
                    attribute=params["attribute"],
                    threshold=float(params["threshold"]),
                )
            case _:
                return Private()  # unknown rule_type → fail closed
    except (KeyError, ValueError, TypeError):
        return Private()  # malformed rule_params → fail closed


def section_visibility(section: Section, viewer: Viewer, *, owner_id: UUID) -> Visibility:
    return can_view(viewer, owner_id=owner_id, rule=rule_for(section), teaser=section.teaser)
