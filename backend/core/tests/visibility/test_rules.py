from uuid import uuid4

from core.visibility.rules import AttributeGate, Audience, Private, Public
from core.visibility.viewer import Viewer


def test_public_grants_everyone():
    assert Public().grants(Viewer()) is True
    assert Public().grants(Viewer(user_id=uuid4())) is True


def test_private_grants_no_one_at_rule_level():
    # Private is owner-only; the owner is granted by the ENGINE, not the rule.
    assert Private().grants(Viewer()) is False
    assert Private().grants(Viewer(user_id=uuid4())) is False


def test_audience_grants_listed_user():
    uid = uuid4()
    rule = Audience(user_ids=frozenset({uid}))
    assert rule.grants(Viewer(user_id=uid)) is True
    assert rule.grants(Viewer(user_id=uuid4())) is False


def test_audience_grants_group_member():
    gid = uuid4()
    rule = Audience(group_ids=frozenset({gid}))
    assert rule.grants(Viewer(group_ids=frozenset({gid}))) is True
    assert rule.grants(Viewer(group_ids=frozenset({uuid4()}))) is False


def test_audience_denies_guest():
    rule = Audience(user_ids=frozenset({uuid4()}), group_ids=frozenset({uuid4()}))
    assert rule.grants(Viewer()) is False


def test_attribute_gate_grants_when_threshold_met():
    rule = AttributeGate(attribute="reputation", threshold=50)
    assert rule.grants(Viewer(attributes={"reputation": 50})) is True
    assert rule.grants(Viewer(attributes={"reputation": 80})) is True


def test_attribute_gate_denies_below_threshold_or_missing():
    rule = AttributeGate(attribute="reputation", threshold=50)
    assert rule.grants(Viewer(attributes={"reputation": 49})) is False
    assert rule.grants(Viewer()) is False  # guest: attribute absent
