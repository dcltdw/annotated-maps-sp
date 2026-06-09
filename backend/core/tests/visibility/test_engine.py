from uuid import uuid4

from core.visibility.engine import Visibility, can_view
from core.visibility.rules import AttributeGate, Private, Public
from core.visibility.viewer import Viewer


def test_owner_always_sees_their_own_section_under_any_rule():
    owner = uuid4()
    me = Viewer(user_id=owner)
    assert can_view(me, owner_id=owner, rule=Private()) is Visibility.VISIBLE
    assert can_view(me, owner_id=owner, rule=AttributeGate("reputation", 999)) is Visibility.VISIBLE


def test_granted_rule_is_visible():
    assert can_view(Viewer(), owner_id=uuid4(), rule=Public()) is Visibility.VISIBLE


def test_denied_without_teaser_is_hidden():
    assert can_view(Viewer(), owner_id=uuid4(), rule=Private(), teaser=False) is Visibility.HIDDEN


def test_denied_with_teaser_is_teaser():
    assert can_view(Viewer(), owner_id=uuid4(), rule=Private(), teaser=True) is Visibility.TEASER
