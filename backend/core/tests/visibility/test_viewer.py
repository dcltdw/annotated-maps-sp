from uuid import uuid4

from core.visibility.viewer import Viewer


def test_guest_viewer_is_unauthenticated():
    v = Viewer()
    assert v.user_id is None
    assert v.is_authenticated is False
    assert v.group_ids == frozenset()
    assert dict(v.attributes) == {}


def test_authenticated_viewer_carries_identity_groups_attributes():
    uid, gid = uuid4(), uuid4()
    v = Viewer(user_id=uid, group_ids=frozenset({gid}), attributes={"reputation": 50})
    assert v.is_authenticated is True
    assert v.user_id == uid
    assert gid in v.group_ids
    assert v.attributes["reputation"] == 50
