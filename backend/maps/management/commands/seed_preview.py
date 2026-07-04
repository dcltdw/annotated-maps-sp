"""Validate a seed GeoJSON file and render a standalone HTML preview map.

Dev tool: `uv run python manage.py seed_preview [path] [--out seed_preview.html]`.
All content strings are HTML-escaped — the tool is safe on untrusted files
(building block for the future GeoJSON import-review feature).
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from maps.seed import SEED_PATH
from maps.seed_schema import SeedValidationError, load_seed_file

_AUTHOR_COLORS = {
    "owner": "#7c3aed",
    "running-friend": "#059669",
    "dimsum-friend": "#d97706",
    "runner": "#2563eb",
    "local": "#dc2626",
}

_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Seed preview</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#map{height:100%;margin:0}.legend{position:absolute;bottom:12px;left:12px;
z-index:1000;background:#fff;padding:8px 12px;font:13px sans-serif;border-radius:6px;
box-shadow:0 1px 4px rgba(0,0,0,.3)}</style></head>
<body><div id="map"></div><div class="legend">__LEGEND__</div>
<script>
var map = L.map('map').setView([42.3601, -71.0589], 13);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  {attribution: '&copy; OpenStreetMap contributors'}).addTo(map);
var FEATURES = __DATA__;
FEATURES.forEach(function (f) {
  var layer;
  if (f.kind === 'Point') {
    layer = L.circleMarker(
      [f.coords[1], f.coords[0]], {radius: 8, color: f.color, fillOpacity: 0.7});
  } else if (f.kind === 'LineString') {
    layer = L.polyline(
      f.coords.map(function (c) { return [c[1], c[0]]; }), {color: f.color, weight: 4});
  } else {
    layer = L.polygon(
      f.coords[0].map(function (c) { return [c[1], c[0]]; }), {color: f.color, fillOpacity: 0.25});
  }
  layer.bindPopup(f.popup).addTo(map);
});
</script></body></html>
"""


class Command(BaseCommand):
    help = "Validate a seed GeoJSON file and write an HTML preview map."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", default=str(SEED_PATH))
        parser.add_argument("--out", default="seed_preview.html")

    def handle(self, *args, **options):
        path = Path(options["path"])
        try:
            seed = load_seed_file(path)
        except (SeedValidationError, OSError) as exc:
            raise CommandError(f"INVALID: {exc}") from exc

        by_slug = {f.properties.slug: f for f in seed.features}
        payload = []
        for feature in seed.features:
            props = feature.properties
            if feature.geometry is not None:
                geo = feature.geometry
            else:
                assert props.parent is not None  # guaranteed: appends carry a parent
                parent_geo = by_slug[props.parent].geometry
                assert parent_geo is not None  # guaranteed: top-level features have geometry
                geo = parent_geo  # appends plot at parent
            rules = "".join(
                f"<li>{html.escape(s.rule)}"
                + (f" → users: {html.escape(', '.join(s.users))}" if s.users else "")
                + (f" → groups: {html.escape(', '.join(s.groups))}" if s.groups else "")
                + (f" ≥ {s.threshold}" if s.threshold is not None else "")
                + f": {html.escape(s.content)}</li>"
                for s in props.sections
            )
            badge = f"<p>⚠ <b>{html.escape(props.docs)}</b></p>" if props.docs else ""
            kind_label = "append on " + html.escape(props.parent) if props.parent else geo.type
            popup = (
                f"<b>{html.escape(props.title or '(append)')}</b>"
                f"<br>by {html.escape(props.author)} · {kind_label}{badge}<ul>{rules}</ul>"
            )
            payload.append(
                {
                    "kind": geo.type,
                    "coords": geo.coordinates if geo.type != "Point" else list(geo.coordinates),
                    "color": _AUTHOR_COLORS[props.author],
                    "popup": popup,
                }
            )

        legend = " ".join(
            f'<span style="color:{c}">●</span> {html.escape(k)}' for k, c in _AUTHOR_COLORS.items()
        )
        data = json.dumps(payload).replace("</", "<\\/")  # never close the script tag
        out = Path(options["out"])
        out.write_text(_PAGE.replace("__LEGEND__", legend).replace("__DATA__", data))
        self.stdout.write(
            self.style.SUCCESS(
                f"OK: {len(seed.top_level)} notes, {len(seed.appends)} appends → {out}"
            )
        )
