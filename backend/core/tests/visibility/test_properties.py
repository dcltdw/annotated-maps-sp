from uuid import uuid4

from hypothesis import given
from hypothesis import strategies as st

from core.visibility.engine import Visibility, can_view
from core.visibility.rules import AttributeGate, Audience, Private, Public
from core.visibility.viewer import Viewer

uuids = st.builds(uuid4)
viewers = st.builds(
    Viewer,
    user_id=st.one_of(st.none(), uuids),
    group_ids=st.frozensets(uuids, max_size=4),
    attributes=st.dictionaries(
        st.sampled_from(["reputation", "age"]),
        st.floats(min_value=0, max_value=100),
        max_size=2,
    ),
)


@given(viewer=viewers, owner=uuids, teaser=st.booleans())
def test_public_is_always_visible(viewer, owner, teaser):
    assert can_view(viewer, owner_id=owner, rule=Public(), teaser=teaser) is Visibility.VISIBLE


@given(viewer=viewers, owner=uuids, teaser=st.booleans())
def test_private_is_never_visible_to_a_non_owner(viewer, owner, teaser):
    if viewer.user_id == owner:
        return  # owner case is covered separately
    assert can_view(viewer, owner_id=owner, rule=Private(), teaser=teaser) is not Visibility.VISIBLE


@given(
    owner=uuids,
    rule=st.sampled_from([Public(), Private(), Audience(), AttributeGate("reputation", 50)]),
    teaser=st.booleans(),
)
def test_owner_is_always_visible_under_any_rule(owner, rule, teaser):
    assert (
        can_view(Viewer(user_id=owner), owner_id=owner, rule=rule, teaser=teaser)
        is Visibility.VISIBLE
    )


@given(
    viewer=viewers,
    owner=uuids,
    threshold=st.floats(min_value=0, max_value=100),
    teaser=st.booleans(),
)
def test_attribute_gate_visible_iff_owner_or_meets_threshold(viewer, owner, threshold, teaser):
    result = can_view(
        viewer, owner_id=owner, rule=AttributeGate("reputation", threshold), teaser=teaser
    )
    rep = viewer.attributes.get("reputation")
    if viewer.user_id == owner or (rep is not None and rep >= threshold):
        assert result is Visibility.VISIBLE
    else:
        assert result is (Visibility.TEASER if teaser else Visibility.HIDDEN)


@given(viewer=viewers, owner=uuids, teaser=st.booleans())
def test_denied_result_is_exactly_teaser_or_hidden_by_flag(viewer, owner, teaser):
    if viewer.user_id == owner:
        return  # exclude the owner (always visible)
    result = can_view(viewer, owner_id=owner, rule=Private(), teaser=teaser)
    assert result is (Visibility.TEASER if teaser else Visibility.HIDDEN)
