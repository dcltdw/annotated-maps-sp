from uuid import uuid4

from core.visibility import AttributeGate, Audience, Private, Public, Viewer, Visibility
from maps.models import Section
from maps.visibility import rule_for, section_visibility


def _section(rule_type, rule_params=None, teaser=False):
    return Section(rule_type=rule_type, rule_params=rule_params or {}, teaser=teaser, content="x")


def test_rule_for_maps_each_type():
    uid, gid = uuid4(), uuid4()
    assert isinstance(rule_for(_section(Section.RuleType.PUBLIC)), Public)
    assert isinstance(rule_for(_section(Section.RuleType.PRIVATE)), Private)
    aud = rule_for(
        _section(Section.RuleType.AUDIENCE, {"user_ids": [str(uid)], "group_ids": [str(gid)]})
    )
    assert isinstance(aud, Audience) and uid in aud.user_ids and gid in aud.group_ids
    gate = rule_for(
        _section(Section.RuleType.ATTRIBUTE_GATE, {"attribute": "reputation", "threshold": 50})
    )
    assert isinstance(gate, AttributeGate) and gate.threshold == 50


def test_section_visibility_uses_the_engine():
    owner = uuid4()
    sec = _section(Section.RuleType.PRIVATE, teaser=True)
    assert section_visibility(sec, Viewer(), owner_id=owner) is Visibility.TEASER
    assert section_visibility(sec, Viewer(user_id=owner), owner_id=owner) is Visibility.VISIBLE
