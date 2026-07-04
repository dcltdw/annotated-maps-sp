# Richer Demo Seed Data — Design

- **Date:** 2026-07-04
- **Status:** Approved design, pending implementation plan
- **Slice:** Demo-content expansion (no product behavior changes)

## Context

The live Boston demo seeds exactly four top-level notes (Castle Island pin, Public
Garden polygon, Charles River loop route, friends-only China Pearl pin) plus one
append. Each carries the full five-tier visibility ladder. This teaches the
visibility feature well but reads as sparse — the map does not look lived-in.

Goal: ~30 curated notes so the first paint is visually interesting, while keeping
the persona-switching story sharp. Content is hand-authored (real Boston places,
real coordinates, fictional-but-plausible tips — same register as the existing
seed).

## Goals

1. **Density with texture** — most notes simple and public; a handful of
   full-ladder showcases; visibility gating present in more than one social
   context.
2. **Seed as data, not code** — adding a note becomes editing a data file, not
   writing ORM calls.
3. **Portable format** — the seed content is a standard GeoJSON document usable
   by external tools, and a small validated step toward the GeoJSON
   import/export seam (production-lenses §7).
4. **Verifiable before deploy** — schema validation in CI plus a visual preview
   tool, so misplaced coordinates or malformed entries fail fast.

## Non-goals

- No product/API/frontend changes. This slice only changes what data the seed
  produces and how it is authored.
- No user-facing GeoJSON import feature (recorded as a backlog seam — see
  "Future seam" below).
- No new demo personas (the four demo logins and the UI hint stay exactly as
  they are).

## Design

### 1. Format: GeoJSON FeatureCollection + Pydantic schema

- **`backend/maps/seed_data.geojson`** — a GeoJSON `FeatureCollection`. Each
  note is a `Feature` with real `Point` / `Polygon` / `LineString` geometry.
  App-specific data lives in `properties`:
  - `slug` (stable unique id, used for idempotent get_or_create and
    parent references)
  - `title` (absent/null for appends, which are untitled today)
  - `author` (persona key: `owner` | `friend` | `runner` | `local`)
  - `parent` (optional: slug of the parent note — marks this feature as an
    append; geometry ignored by the loader for appends, matching the model)
  - `sections`: ordered list of `{rule_type, rule_params?, teaser?, content}`
    mirroring `Section` semantics. `rule_params` uses symbolic keys
    (`{"users": ["friend"]}`, `{"groups": ["running-club"]}`) that the loader
    resolves to real ids at seed time — the JSON never contains database ids.
- **`backend/maps/seed_schema.py`** — Pydantic models (`SeedFile`,
  `SeedFeature`, `SeedSection`, geometry models) that parse and validate the
  file. Constraints: rule types restricted to `Section.RuleType` values;
  author/user/group keys restricted to the known cast; coordinate arity checked
  per geometry kind; polygon rings closed; slugs unique; `parent` references
  must resolve to a feature in the same file; `extra="forbid"` so unknown
  fields fail loudly. django-ninja already ships Pydantic — no new dependency.
- **Geometry lint (beyond shape validation):** every coordinate must fall
  inside a Greater Boston bounding box (lng −71.20…−70.90, lat 42.25…42.45);
  LineStrings ≥ 2 vertices; polygons GEOS-valid. Catches transposed lng/lat and
  hand-plotting slips mechanically.

### 2. Loader

`maps/seed.py` keeps the cast (tenant, four personas, groups, map) in code and
gains a typed loader:

1. Parse `seed_data.geojson` through `seed_schema` (raises on any violation).
2. Build a symbol table: persona key → User, group key → Group.
3. Create notes in two passes (top-level first, then appends), idempotently by
   `(tenant, map, slug)` — which requires persisting the slug. **Decision:**
   reuse `get_or_create` on `(tenant, map, author, title)` for top-level notes
   (as today) and `(tenant, map, author, parent)` for appends, keeping slugs a
   file-internal concept — no model change. Consequence the content plan must
   respect (schema-enforced): at most one append per (author, parent) pair,
   and top-level titles unique per author. If title collisions ever matter,
   a `seed_slug` column is the upgrade path; out of scope now.
4. `seed_demo --refresh` behavior unchanged: hard-delete `is_seed` notes,
   rebuild from the file, never touch user-created notes.

The `build_boston_demo()` return contract (used by tests) keeps returning the
cast; note-specific keys are replaced by a `notes_by_slug` mapping.

### 3. Content plan (~30 notes)

| Category | Count | Geometry | Notes |
|---|---|---|---|
| Restaurants & cafés | 12–14 | Point | Chinatown (3–4), North End (4–5), scattered (Back Bay, Cambridge). Authored mostly by `friend` and `local`. |
| Running routes | 4 | LineString | Southie/Harborwalk, Esplanade→BU extension, Southwest Corridor, Common–Garden shakeout. Authored by `runner`. |
| Parks & areas | 4–5 | Polygon | Boston Common, Christopher Columbus Park, a North End waterfront stretch, one Cambridge green. |
| One-off tips | 6–8 | Point | Viewpoints, T-station gotchas, water fountains, a photo spot. Mixed authors. |

**Visibility texture (the load-bearing part):**

- ~60% of notes: 1–2 sections, public (or public + one gated extra).
- 4–5 notes: full five-tier ladder (the showcases, spread across categories).
- 2–3 whole-note-gated notes (China Pearl pattern): at least one friends-only
  and one group-gated.
- 4–5 appends across different authors and parents (social feel).
- All geometry within the initial zoom-12 downtown viewport so the first paint
  is dense; routes may extend slightly beyond.

**Content register:** real place names, real coordinates, fictional tips —
consistent with the existing seed. No claims a visitor could act on to their
detriment (hours, prices).

### 4. New group: Dim sum crew

`Group(name="Dim sum crew")` with `friend` and `local` as members. Group-gated
content then exists in two social contexts (running + food), so persona
switching re-filters visibly across the whole map, not just athletic notes.
No persona changes; the demo-login hint stays accurate.

### 5. `seed_preview` tool

A dev-facing management command, `manage.py seed_preview [path]` (defaults to
the shipped file):

- Runs schema validation + geometry lint (same `seed_schema` code path) and
  prints a pass/fail report.
- Writes a standalone `seed_preview.html`: a Leaflet/MapLibre map plotting all
  features — color-coded by geometry kind and author, popups showing title,
  author, and each section's visibility rule. Open in a browser to eyeball
  placement and content in one pass.
- **All content strings are HTML-escaped** when building the page, so the tool
  is safe on untrusted files from day one (it is a future building block for
  the import-review feature, not just a dev convenience).
- Output file is gitignored.

### 6. Verification

1. **CI schema test** — the shipped `seed_data.geojson` parses through
   `seed_schema` with zero violations (this makes runtime validation
   effectively static for our file).
2. **Seed tests extended** — counts by category/author, idempotency
   (`build_boston_demo()` twice → no duplicates), `--refresh` spares
   non-seed notes, appends attach to the right parents, group membership.
3. **Geometry lint test** — bounding box + validity assertions over the file.
4. **Visual pass** — `seed_preview` output reviewed by a human, plus one
   headless-Playwright screenshot of the running app against the new seed
   before merge (final in-app confirmation; the preview tool replaces the
   iterative placement loop).

### 7. Risks & mitigations

- **Payload/render size:** ~30 notes with sections is a trivial payload and
  well within MapLibre comfort; no pagination or clustering needed at this
  scale. (If seed ever grows 10×, revisit — noted, not built.)
- **Sandbox global cap (2000 rows):** ~35 notes + ~80 sections is nowhere near
  it; the cap counts user-created rows anyway.
- **`--refresh` on deploy deletes and rebuilds all seed notes** — unchanged
  behavior, but the first deploy after this slice visibly replaces the old
  four-note demo. Deliberate.
- **Coordinate errors:** covered by lint + preview + screenshot (three layers).

## Future seam (recorded, not built)

User-facing **GeoJSON import review**: a user receives a third-party GeoJSON
file and wants to (1) security-check it (sandboxed parse, size/vertex limits,
content sanitization for popup XSS), (2) verify it matches its description
(geographic containment, geometry-kind expectations), and (3) visually approve
it overlaid on existing map data (duplicate/near-duplicate detection,
accept/reject/request-changes). This slice's Pydantic schema, geometry lint,
and escaping preview renderer are its building blocks. Recorded as a 🟡 item
under production-lenses §7 in this slice; its own spec when prioritized.

## Testing summary

`uv run pytest` (schema test, seed tests, lint test) + `manage.py seed_preview`
visual pass + one in-app screenshot. No frontend test changes expected (e2e
stubs use their own fixtures, not the seed).
