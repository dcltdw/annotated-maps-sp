import json

import pytest
from django.core.management import CommandError, call_command


def _valid_doc(content="hello"):
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-71.06, 42.36]},
                "properties": {
                    "slug": "a-pin",
                    "title": "A pin",
                    "author": "local",
                    "docs": "load-bearing",
                    "sections": [{"rule": "public", "content": content}],
                },
            }
        ],
    }


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
