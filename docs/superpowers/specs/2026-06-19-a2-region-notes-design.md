# A2 — Region / Boundary Notes — Design

- **Status:** approved (brainstorming) — 2026-06-19
- **Goal:** Extend a note's anchor from a point to a **shape** — a polygon (area), a line (route), or a circle (drawn as an N-gon polygon) — so users can annotate areas and routes, not just pins. Everything that makes the app distinctive (section-level visibility, teasers, appends, CRUD, sandbox/authz) is **geometry-agnostic and reused unchanged**.
- **Relationship:** a feature slice on the merged point-note core (foundation → A1.3c → hardening → A4 sandbox/moderation). Independent of the A4 deploy (pure code). Real auth remains deferred to A5.
- **Scope decision (d′):** support polygon + line + circle, where **circle is only a drawing tool that emits a polygon** — so storage/API/rendering deal with exactly three anchor kinds: point, polygon, line. Built in layers (polygon → line → circle), each a clean stopping point.

## 1. Data model

`Note` keeps `point` and gains two nullable native-PostGIS fields (one migration, no data migration of existing rows):
- `area = gis.PolygonField(null=True, blank=True)` — freehand polygons **and** circles (a circle is a regular N-gon polygon, 16–20 sides; visually circular at map zoom, always valid/convex).
- `path = gis.LineStringField(null=True, blank=True)` — routes / boundary lines.

**Invariant:** a note has **exactly one** of `{point, area, path}` non-null. Enforced in the write API (422 otherwise). Appends remain point-less child notes (unchanged — appends carry no geometry).

"Circle" never appears in the model, API, or render layer — it is purely a UI draw mode whose output is a polygon stored in `area`.

## 2. Draw abstraction layer (swappable)

terra-draw is wrapped behind our own port so the rest of the app never imports it directly. New directory `frontend/src/lib/draw/`:

- **`types.ts`** — our own geometry type, independent of terra-draw:
  ```ts
  export type DrawMode = "polygon" | "line" | "circle";
  export type DrawShape =
    | { kind: "polygon"; coordinates: [number, number][] }  // outer ring, [lng,lat]
    | { kind: "line"; coordinates: [number, number][] };    // path, [lng,lat]
  ```
  (Note: `DrawMode` has three values; `DrawShape.kind` has two — `circle` mode produces a `polygon` shape.)
- **`ShapeDrawer` interface** — the port the app depends on:
  ```ts
  export interface ShapeDrawer {
    mount(map: MaplibreMap): void;
    startDraw(mode: DrawMode, onComplete: (shape: DrawShape) => void): void;
    editShape(shape: DrawShape, onChange: (shape: DrawShape) => void): void;
    cancel(): void;
    destroy(): void;
  }
  ```
- **`TerraDrawAdapter`** — the **only** file that imports terra-draw + its maplibre adapter; translates terra-draw features/events ↔ `DrawShape`. The circle mode is configured to emit a polygon (verified in the integration spike).
- **`FakeShapeDrawer`** — a test double implementing `ShapeDrawer` (drives `onComplete`/`onChange` synchronously with canned shapes); component + e2e tests inject it, so they never load terra-draw or need WebGL.
- A small **factory** (e.g. `createShapeDrawer()`) selects the implementation. Swapping to hand-rolled or another library = write one new adapter; no consumer changes.

The rest of the app (MapView / MapScreen / editor) imports only `ShapeDrawer`, `DrawShape`, and the factory.

## 3. Rendering & selection

Alongside the existing point **markers**, MapView adds two maplibre GeoJSON layers built from the visibility-filtered notes:
- a **fill + outline** layer for `area` notes (polygons, including circles), and
- a **line** layer for `path` notes (routes).

Clicking a fill or line **selects that note** and opens the existing `NotePanel` (same selection path as a marker). Hidden notes (no visible sections for the viewer) are simply not returned by the API — identical to points today. Styling: a low-opacity fill + a solid outline for areas; a solid stroke for lines; a selected/hover state. terra-draw's transient draw geometry is separate from these display layers.

## 4. Editing scope (MVP)

- **Create:** choose a draw mode (polygon / line / circle), draw the shape via the drawer, then fill in sections in the existing `NoteEditor`. The create payload carries the `DrawShape` instead of `lng`/`lat`.
- **Edit:** re-open the editor for **sections** exactly as today; **geometry** is changed by re-entering draw mode. We will support **vertex dragging** via the drawer's `editShape` if the integration spike shows terra-draw's select mode is clean; otherwise the MVP falls back to **redraw-to-change** (draw a replacement shape). Either way the `editShape` port keeps the choice open without consumer changes.

The existing point-note create/edit flow is preserved (a point note is still placed with the draft pin and carries `lng`/`lat`).

## 5. Backend API & validation

`NoteIn` / `NoteUpdateIn` / `NoteOut` / `NoteEditOut` gain an **optional shape** representation parallel to today's `lng`/`lat`, e.g. a nullable `shape: {kind: "polygon"|"line", coordinates: [[lng,lat], …]} | None`. The write path:
- **Exactly-one-anchor** validation: precisely one of (`lng`+`lat`) or `shape` is provided → else 422.
- **Geometry validity:** a polygon ring is closed, has ≥3 distinct vertices, and is non-self-intersecting (GEOS `.valid`); a line has ≥2 points. Invalid → 422.
- `create_note` / `update_note` build a `Polygon` or `LineString` (or `Point`) and set the matching field, leaving the others null.
- The atomic version-claim concurrency, author/sandbox authorization, the `editable` flag, section hard-replace, and append rules are **unchanged**.

`NoteOut` returns the anchor so the frontend can render it: `lng`/`lat` for points (as today) plus `shape` for area/path notes.

## 6. Build sequence (layered)

1. **Polygon layer** — integration spike + `TerraDrawAdapter` + `ShapeDrawer`/`FakeShapeDrawer`; `Note.area` + migration; API shape in/out + validation (polygon); fill rendering + click-select; create/edit wiring. Delivers the headline.
2. **Line layer** — `Note.path` + the line draw mode + line rendering. Reuses the abstraction.
3. **Circle layer** — a circle draw mode emitting a polygon into the existing `area` path + render (already covered by the fill layer). Cheapest.

## 7. Testing

- **Backend:** create/read a polygon note and a line note; the exactly-one-anchor rule (point-only, area-only, path-only pass; zero or two anchors → 422); invalid-geometry rejection (self-intersecting polygon, 1-point line); visibility filtering still hides fully-hidden region notes; sandbox/authz unchanged for region notes.
- **Frontend:** the draw abstraction (`TerraDrawAdapter` translation tested where practical; `FakeShapeDrawer` drives flows); create-a-region flow via `FakeShapeDrawer`; rendering of fill/line layers from notes; selection opens the panel.
- **e2e:** an author-loop for a region note using the injected `FakeShapeDrawer` (no real terra-draw/WebGL dependency in CI).
- Full gates as usual (backend pytest+ruff+format+mypy+makemigrations; frontend test+lint+tsc+build).

## Out of scope

Multi-part or holed polygons; GPX/GeoJSON import; vertex snapping; area/length measurement readouts; true geometric circles (we use N-gon polygons); converting existing point notes to regions. Real auth (A5), additional shape types beyond these three.
