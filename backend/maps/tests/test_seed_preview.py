import json
import re

import pytest
from django.core.management import CommandError, call_command


def _valid_doc(content="hello", title="A pin", docs="load-bearing"):
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-71.06, 42.36]},
                "properties": {
                    "slug": "a-pin",
                    "title": title,
                    "author": "local",
                    "docs": docs,
                    "sections": [{"rule": "public", "content": content}],
                },
            }
        ],
    }


# The .legend div's markup for the "owner" persona — used to detect whether the
# legend HTML got spliced a second time into the JSON payload (placeholder collision).
_OWNER_LEGEND_SPAN = '<span style="color:#7c3aed">●</span> owner'


def test_preview_writes_html_for_valid_file(tmp_path):
    src = tmp_path / "seed.geojson"
    src.write_text(json.dumps(_valid_doc()))
    out = tmp_path / "preview.html"
    call_command("seed_preview", str(src), out=str(out))
    html = out.read_text()
    assert "A pin" in html
    assert "load-bearing" in html  # docs badge surfaces


def test_preview_escapes_content(tmp_path):
    src = tmp_path / "seed.geojson"
    src.write_text(json.dumps(_valid_doc(content='<script>alert("x")</script>')))
    out = tmp_path / "preview.html"
    call_command("seed_preview", str(src), out=str(out))
    html = out.read_text()
    assert '<script>alert("x")</script>' not in html  # raw payload must not appear
    assert "&lt;script&gt;" in html  # escaped form does


def test_preview_content_equal_to_legend_placeholder_does_not_leak_raw_legend(tmp_path):
    # A seed "content" field that happens to equal the internal __LEGEND__ token
    # must not cause the raw (unescaped) legend HTML to get spliced into the JSON
    # payload embedded in the <script> block — that would break out of the JS
    # string via the legend's unescaped `"` characters. See regression: the two
    # template substitutions must not be ordered data-then-legend.
    src = tmp_path / "seed.geojson"
    src.write_text(json.dumps(_valid_doc(content="__LEGEND__")))
    out = tmp_path / "preview.html"
    call_command("seed_preview", str(src), out=str(out))
    page = out.read_text()

    # The legend markup must be rendered exactly once (in the .legend div) — not
    # a second time inside the script payload where the content placeholder was.
    assert page.count(_OWNER_LEGEND_SPAN) == 1

    # The escaped content ("__LEGEND__" has no HTML metacharacters, so escaping
    # is a no-op) must survive literally inside the JSON payload.
    match = re.search(r"var FEATURES = (\[.*\]);\n", page)
    assert match is not None
    payload = json.loads(match.group(1))  # a collision would corrupt this JSON
    assert "__LEGEND__" in payload[0]["popup"]


def test_preview_title_and_docs_equal_to_placeholders_do_not_corrupt_payload(tmp_path):
    # Same collision, but via the "title" (-> __LEGEND__) and "docs" (-> __DATA__)
    # fields, which also flow into the popup HTML embedded in the JSON payload.
    src = tmp_path / "seed.geojson"
    src.write_text(json.dumps(_valid_doc(title="__LEGEND__", docs="__DATA__")))
    out = tmp_path / "preview.html"
    call_command("seed_preview", str(src), out=str(out))
    page = out.read_text()

    assert page.count(_OWNER_LEGEND_SPAN) == 1

    match = re.search(r"var FEATURES = (\[.*\]);\n", page)
    assert match is not None
    payload = json.loads(match.group(1))  # a collision would corrupt this JSON
    assert "__LEGEND__" in payload[0]["popup"]
    assert "__DATA__" in payload[0]["popup"]


def test_preview_escapes_title_and_docs(tmp_path):
    src = tmp_path / "seed.geojson"
    src.write_text(json.dumps(_valid_doc(title="<b>x</b>", docs="<b>y</b>")))
    out = tmp_path / "preview.html"
    call_command("seed_preview", str(src), out=str(out))
    page = out.read_text()
    assert "<b>x</b>" not in page
    assert "<b>y</b>" not in page
    assert "&lt;b&gt;x&lt;/b&gt;" in page
    assert "&lt;b&gt;y&lt;/b&gt;" in page


def test_preview_fails_on_invalid_file(tmp_path):
    src = tmp_path / "seed.geojson"
    doc = _valid_doc()
    doc["features"][0]["properties"]["author"] = "mallory"
    src.write_text(json.dumps(doc))
    with pytest.raises(CommandError):
        call_command("seed_preview", str(src), out=str(tmp_path / "x.html"))


def test_preview_defaults_to_shipped_seed(tmp_path):
    out = tmp_path / "shipped.html"
    call_command("seed_preview", out=str(out))  # no path arg
    assert "Charles River loop" in out.read_text()
