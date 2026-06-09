# A1.1 — Visibility Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the section-level visibility engine — `can_view(viewer, …) → VISIBLE | TEASER | HIDDEN` over the four rule types (Public, Audience, Attribute-gate, Private) — as a pure, DB-free domain module with property-based tests.

**Architecture:** A standalone `core/visibility/` package: an immutable `Viewer` value object, a `VisibilityRule` hierarchy (`Public`, `Audience`, `AttributeGate`, `Private`) each answering `grants(viewer) → bool`, and a pure `can_view()` that resolves **owner-sees-all → rule grant → teaser/hidden**. No Django models, no DB, no API, no frontend — those wrap this engine in A1.2 / A1.3. The isolation is deliberate: this is the product's differentiator and is security-critical, so it is built and **property-tested on its own first**. It is the single source of truth for "who can see what" (centralized policy — spec §6).

**Tech Stack:** Python 3.12 (dataclasses, `enum`), Hypothesis (property-based tests), pytest. Spec: `docs/superpowers/specs/2026-06-08-annotated-maps-design.md` §6.

**Scope guard:** This is A1.1 ONLY — the pure engine. Do NOT add Django models, API routes, serialization, persistence, or any mapping from DB rows to these domain objects (that is A1.2). Build only what each task specifies.

---

## File Structure

```
backend/
  pyproject.toml                         # + hypothesis (dev dep)
  core/
    visibility/
      __init__.py                        # public exports
      viewer.py                          # Viewer value object
      rules.py                           # VisibilityRule + Public/Private/Audience/AttributeGate
      engine.py                          # Visibility enum + can_view()
    tests/
      visibility/
        __init__.py
        test_viewer.py
        test_rules.py
        test_engine.py
        test_properties.py               # Hypothesis invariants
```

All commands run from `backend/`. The engine modules have **no Django imports** — the tests don't need `@pytest.mark.django_db` (pure functions over value objects).

---

## Task 1: Hypothesis dep + `Viewer` value object

**Files:**
- Modify: `backend/pyproject.toml` (add `hypothesis` dev dep)
- Create: `backend/core/visibility/__init__.py`, `backend/core/visibility/viewer.py`, `backend/core/tests/visibility/__init__.py`, `backend/core/tests/visibility/test_viewer.py`

- [ ] **Step 1: Add Hypothesis** — run from `backend/`: `uv add --dev hypothesis`

- [ ] **Step 2: Write the failing test** (`backend/core/tests/visibility/test_viewer.py`); also create empty `backend/core/tests/visibility/__init__.py`:
```python
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
```

- [ ] **Step 3: Run to verify it FAILS:** `uv run pytest core/tests/visibility/test_viewer.py -v` — expected: ImportError (`core.visibility` doesn't exist).

- [ ] **Step 4: Create `backend/core/visibility/__init__.py`** (empty for now) and **`backend/core/visibility/viewer.py`**:
```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class Viewer:
    """Who is looking. A guest is `Viewer()` (no user_id, no groups, no attributes)."""

    user_id: UUID | None = None
    group_ids: frozenset[UUID] = frozenset()
    attributes: Mapping[str, float] = field(default_factory=dict)

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None
```

- [ ] **Step 5: Run to verify it PASSES:** `uv run pytest core/tests/visibility/test_viewer.py -v`

- [ ] **Step 6: Commit:**
```bash
git add backend/pyproject.toml backend/uv.lock backend/core/visibility/ backend/core/tests/visibility/
git commit -m "feat(a1): Viewer value object + Hypothesis dev dep"
```

---

## Task 2: `Public` and `Private` rules

**Files:**
- Create: `backend/core/visibility/rules.py`, `backend/core/tests/visibility/test_rules.py`

- [ ] **Step 1: Write the failing test** (`backend/core/tests/visibility/test_rules.py`):
```python
from uuid import uuid4

from core.visibility.rules import Private, Public
from core.visibility.viewer import Viewer


def test_public_grants_everyone():
    assert Public().grants(Viewer()) is True
    assert Public().grants(Viewer(user_id=uuid4())) is True


def test_private_grants_no_one_at_rule_level():
    # Private is owner-only; the owner is granted by the ENGINE, not the rule.
    assert Private().grants(Viewer()) is False
    assert Private().grants(Viewer(user_id=uuid4())) is False
```

- [ ] **Step 2: Run to verify it FAILS:** `uv run pytest core/tests/visibility/test_rules.py -v` (ImportError).

- [ ] **Step 3: Create `backend/core/visibility/rules.py`:**
```python
from __future__ import annotations

from dataclasses import dataclass

from core.visibility.viewer import Viewer


class VisibilityRule:
    """A rule answers a single question: does it grant this viewer access?
    Owner-sees-all is handled by the engine, not by individual rules."""

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
```

- [ ] **Step 4: Run to verify it PASSES:** `uv run pytest core/tests/visibility/test_rules.py -v`

- [ ] **Step 5: Commit:**
```bash
git add backend/core/visibility/rules.py backend/core/tests/visibility/test_rules.py
git commit -m "feat(a1): Public and Private visibility rules"
```

---

## Task 3: `Audience` rule (specific users and/or named groups)

**Files:**
- Modify: `backend/core/visibility/rules.py`, `backend/core/tests/visibility/test_rules.py`

- [ ] **Step 1: Add the failing tests** to `backend/core/tests/visibility/test_rules.py` (append; add `Audience` to the import line):
```python
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
```

- [ ] **Step 2: Run to verify it FAILS:** `uv run pytest core/tests/visibility/test_rules.py -k audience -v` (ImportError on `Audience`).

- [ ] **Step 3: Add `Audience` to `backend/core/visibility/rules.py`:**
```python
from uuid import UUID  # add to the imports at the top


@dataclass(frozen=True)
class Audience(VisibilityRule):
    """Visible to specific users and/or members of specific groups."""

    user_ids: frozenset[UUID] = frozenset()
    group_ids: frozenset[UUID] = frozenset()

    def grants(self, viewer: Viewer) -> bool:
        if viewer.user_id is not None and viewer.user_id in self.user_ids:
            return True
        return bool(self.group_ids & viewer.group_ids)
```

- [ ] **Step 4: Run to verify it PASSES:** `uv run pytest core/tests/visibility/test_rules.py -k audience -v`

- [ ] **Step 5: Commit:**
```bash
git add backend/core/visibility/rules.py backend/core/tests/visibility/test_rules.py
git commit -m "feat(a1): Audience visibility rule (users + groups)"
```

---

## Task 4: `AttributeGate` rule (viewer attribute ≥ threshold)

**Files:**
- Modify: `backend/core/visibility/rules.py`, `backend/core/tests/visibility/test_rules.py`

- [ ] **Step 1: Add the failing tests** to `test_rules.py` (append; add `AttributeGate` to the import line):
```python
def test_attribute_gate_grants_when_threshold_met():
    rule = AttributeGate(attribute="reputation", threshold=50)
    assert rule.grants(Viewer(attributes={"reputation": 50})) is True
    assert rule.grants(Viewer(attributes={"reputation": 80})) is True


def test_attribute_gate_denies_below_threshold_or_missing():
    rule = AttributeGate(attribute="reputation", threshold=50)
    assert rule.grants(Viewer(attributes={"reputation": 49})) is False
    assert rule.grants(Viewer()) is False  # guest: attribute absent
```

- [ ] **Step 2: Run to verify it FAILS:** `uv run pytest core/tests/visibility/test_rules.py -k attribute_gate -v` (ImportError on `AttributeGate`).

- [ ] **Step 3: Add `AttributeGate` to `backend/core/visibility/rules.py`:**
```python
@dataclass(frozen=True)
class AttributeGate(VisibilityRule):
    """Visible when the viewer's attribute meets a numeric threshold
    (e.g. reputation >= 50). A missing attribute (guest) never meets it."""

    attribute: str
    threshold: float

    def grants(self, viewer: Viewer) -> bool:
        value = viewer.attributes.get(self.attribute)
        return value is not None and value >= self.threshold
```

- [ ] **Step 4: Run to verify it PASSES:** `uv run pytest core/tests/visibility/test_rules.py -k attribute_gate -v`

- [ ] **Step 5: Commit:**
```bash
git add backend/core/visibility/rules.py backend/core/tests/visibility/test_rules.py
git commit -m "feat(a1): AttributeGate visibility rule (threshold)"
```

---

## Task 5: The engine — `Visibility` enum + `can_view()`

**Files:**
- Create: `backend/core/visibility/engine.py`, `backend/core/tests/visibility/test_engine.py`
- Modify: `backend/core/visibility/__init__.py` (public exports)

- [ ] **Step 1: Write the failing test** (`backend/core/tests/visibility/test_engine.py`):
```python
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
```

- [ ] **Step 2: Run to verify it FAILS:** `uv run pytest core/tests/visibility/test_engine.py -v` (ImportError).

- [ ] **Step 3: Create `backend/core/visibility/engine.py`:**
```python
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
    then teaser-vs-hidden for the denied case. Pure and deterministic."""
    if viewer.user_id is not None and viewer.user_id == owner_id:
        return Visibility.VISIBLE
    if rule.grants(viewer):
        return Visibility.VISIBLE
    return Visibility.TEASER if teaser else Visibility.HIDDEN
```

- [ ] **Step 4: Set the package's public exports** — `backend/core/visibility/__init__.py`:
```python
from core.visibility.engine import Visibility, can_view
from core.visibility.rules import (
    AttributeGate,
    Audience,
    Private,
    Public,
    VisibilityRule,
)
from core.visibility.viewer import Viewer

__all__ = [
    "Viewer",
    "VisibilityRule",
    "Public",
    "Private",
    "Audience",
    "AttributeGate",
    "Visibility",
    "can_view",
]
```

- [ ] **Step 5: Run to verify it PASSES:** `uv run pytest core/tests/visibility/test_engine.py -v`

- [ ] **Step 6: Commit:**
```bash
git add backend/core/visibility/engine.py backend/core/visibility/__init__.py backend/core/tests/visibility/test_engine.py
git commit -m "feat(a1): can_view engine (owner/grant/teaser/hidden)"
```

---

## Task 6: Property-based invariants (Hypothesis)

**Files:**
- Create: `backend/core/tests/visibility/test_properties.py`

- [ ] **Step 1: Write the property tests** (`backend/core/tests/visibility/test_properties.py`). These encode the security-critical invariants over *generated* viewers/rules:
```python
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
    assert can_view(Viewer(user_id=owner), owner_id=owner, rule=rule, teaser=teaser) is Visibility.VISIBLE


@given(viewer=viewers, owner=uuids, threshold=st.floats(min_value=0, max_value=100), teaser=st.booleans())
def test_attribute_gate_visible_iff_owner_or_meets_threshold(viewer, owner, threshold, teaser):
    result = can_view(viewer, owner_id=owner, rule=AttributeGate("reputation", threshold), teaser=teaser)
    rep = viewer.attributes.get("reputation")
    if viewer.user_id == owner or (rep is not None and rep >= threshold):
        assert result is Visibility.VISIBLE
    else:
        assert result is (Visibility.TEASER if teaser else Visibility.HIDDEN)


@given(viewer=viewers, owner=uuids, teaser=st.booleans())
def test_denied_result_is_exactly_teaser_or_hidden_by_flag(viewer, owner, teaser):
    # Use Private with a guaranteed non-owner so the rule always denies.
    if viewer.user_id == owner:
        return
    result = can_view(viewer, owner_id=owner, rule=Private(), teaser=teaser)
    assert result is (Visibility.TEASER if teaser else Visibility.HIDDEN)
```

- [ ] **Step 2: Run them:** `uv run pytest core/tests/visibility/test_properties.py -v` — expected: PASS (Hypothesis explores hundreds of cases per property). If a property fails, Hypothesis prints a minimal counterexample — that's a real engine bug; fix `engine.py`/`rules.py`, don't weaken the property.

- [ ] **Step 3: Full check** — `uv run pytest -q` (all green), `uv run ruff check .` and `uv run ruff format --check .` clean, `uv run mypy .` clean.

- [ ] **Step 4: Commit:**
```bash
git add backend/core/tests/visibility/test_properties.py
git commit -m "test(a1): property-based invariants for the visibility engine"
```

---

## Definition of Done

- [ ] `core/visibility/` exports `Viewer`, the four rules, `Visibility`, and `can_view`.
- [ ] All unit tests + Hypothesis property tests pass; `ruff`, `ruff format --check`, and `mypy` clean; full `uv run pytest` green.
- [ ] Invariants hold: Public always visible; Private never visible to a non-owner; owner always visible; AttributeGate visible iff owner-or-threshold-met; denied ⇒ teaser-or-hidden by flag.
- [ ] No Django/DB/API/frontend code added (that's A1.2 / A1.3).

## Out of scope (later)

A1.2 maps Django `Note`/`Section` rows + the resolved current `Viewer` (from auth/preview-as) onto these domain objects and exposes a visibility-filtered API; A1.3 renders it. Admin-bypass-of-Private and reputation *earning* remain deferred per the spec.
