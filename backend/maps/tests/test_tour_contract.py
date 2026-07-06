# backend/maps/tests/test_tour_contract.py
"""Cross-layer guards for the demo tour's two string contracts.

The tour (frontend) finds the showcase note by title and the switch-target
viewer by display name. If this test fails you are editing something the
demo tour depends on — read docs/superpowers/specs/2026-07-04-demo-tour-design.md
and change both sides in the same PR.
"""

import json
import re
from pathlib import Path

from maps.seed import _PERSONAS, SEED_PATH

REPO_ROOT = Path(__file__).resolve().parents[3]
TOUR_STEPS_TS = REPO_ROOT / "frontend" / "src" / "tour" / "tourSteps.ts"


def _ts_constant(name: str) -> str:
    source = TOUR_STEPS_TS.read_text()
    match = re.search(rf'export const {name} = "([^"]+)"', source)
    assert match, f"{name} not found in {TOUR_STEPS_TS}"
    return match.group(1)


def test_showcase_title_exists_in_seed_with_full_ladder():
    title = _ts_constant("SHOWCASE_TITLE")
    doc = json.loads(SEED_PATH.read_text())
    matches = [f for f in doc["features"] if f["properties"].get("title") == title]
    assert len(matches) == 1, f"seed must contain exactly one note titled {title!r}"
    rules = {s["rule"] for s in matches[0]["properties"]["sections"]}
    assert {"public", "audience", "attribute_gate", "private"} <= rules


def test_tour_persona_exists_in_cast():
    name = _ts_constant("TOUR_PERSONA_NAME")
    display_names = {display for display, _email, _rep in _PERSONAS.values()}
    assert name in display_names


def test_showcase_constants_agree_across_layers():
    from maps.seed_schema import SHOWCASE_TITLE

    assert _ts_constant("SHOWCASE_TITLE") == SHOWCASE_TITLE
