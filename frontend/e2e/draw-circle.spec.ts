import { expect, test } from "./fixtures";

// ---------------------------------------------------------------------------
// Draw → save e2e for circle (area) notes.
//
// A circle is a one-way drawing tool: the real terra-draw circle adapter emits
// a many-sided polygon. So we inject the same fake ShapeDrawer as draw-polygon
// but click the "Draw circle" button. The fake's __emitShape fires a polygon
// shape, which flows through the existing editor→createNote→area→render path
// unchanged. This test proves the circle entry point produces a polygon area
// note end-to-end.
// ---------------------------------------------------------------------------

const MINIMAL_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#e8e8e8" } }],
};

const MAP = { id: "m1", name: "Greater Boston", lng: -71.0589, lat: 42.3601, zoom: 13 };
const VIEWERS = [{ id: "owner", display_name: "You (owner)", reputation: 100 }];
const GROUPS = [{ id: "rc", name: "Running club" }];

// The polygon ring the fake will "draw" (a closed [lng,lat] ring approximating
// a circle — the real circle adapter emits a many-sided polygon; exact vertices
// don't matter for the assertion).
const RING: [number, number][] = [
  [-71.06, 42.36],
  [-71.05, 42.36],
  [-71.05, 42.37],
  [-71.06, 42.37],
  [-71.06, 42.36],
];

interface StoredSection {
  order: number;
  content: string;
  rule_type: string;
  rule_params: Record<string, unknown>;
  teaser: boolean;
  teaser_text: string;
}
interface StoredNote {
  id: string;
  author_id: string;
  title: string;
  lng: number | null;
  lat: number | null;
  shape: { kind: string; coordinates: [number, number][] } | null;
  version: number;
  sections: StoredSection[];
}

// Region-aware NoteOut: carries the stored `shape` (and null lng/lat) so MapView's
// region effect renders it into the `regions` source — unlike authoring.spec's
// point-only helper which always returns shape:null.
function toNoteOut(n: StoredNote, previewAs: string | null) {
  return {
    id: n.id,
    author_id: n.author_id,
    title: n.title,
    lng: n.lng,
    lat: n.lat,
    editable: previewAs === n.author_id,
    shape: n.shape,
    sections: n.sections.map((s, i) => ({
      id: `${n.id}-s${i}`,
      order: s.order,
      visibility: "visible" as const,
      content: s.content,
      rule_type: s.rule_type,
      rule_label: s.rule_type === "public" ? "Public" : "Private",
      teaser_text: null,
    })),
    appends: [],
  };
}

test.describe("draw circle (injected fake drawer)", () => {
  test("draw circle → editor → save POSTs a polygon shape and renders the region", async ({
    page,
  }) => {
    // --- Inject the fake ShapeDrawer before the app initialises. ----------
    await page.addInitScript(() => {
      let cb: ((shape: unknown) => void) | null = null;
      (window as unknown as { __shapeDrawerOverride?: unknown }).__shapeDrawerOverride = {
        mount() {},
        startDraw(_mode: string, onComplete: (s: unknown) => void) {
          cb = onComplete;
        },
        editShape() {},
        cancel() {
          cb = null;
        },
        destroy() {
          cb = null;
        },
      };
      (window as unknown as { __emitShape?: (c: number[][]) => void }).__emitShape = (
        coords: number[][],
      ) => cb?.({ kind: "polygon", coordinates: coords });
    });

    // --- Stateful notes stub; capture the create POST body. ---------------
    const notes: StoredNote[] = [];
    let nextId = 100;
    let postBody: {
      title?: string;
      lng?: number;
      lat?: number;
      shape?: { kind: string; coordinates: [number, number][] };
      sections?: StoredSection[];
    } | null = null;

    await page.route("**/styles/positron**", (r) => r.fulfill({ json: MINIMAL_STYLE }));
    await page.route("**/api/v1/maps", (r) => r.fulfill({ json: [MAP] }));
    await page.route("**/api/v1/maps/*/viewers", (r) => r.fulfill({ json: VIEWERS }));
    await page.route("**/api/v1/maps/*/groups", (r) => r.fulfill({ json: GROUPS }));

    await page.route("**/api/v1/maps/*/notes**", (route) => {
      const method = route.request().method();
      if (method === "GET") {
        const previewAs =
          new URL(route.request().url()).searchParams.get("preview_as") ?? null;
        return route.fulfill({ json: notes.map((n) => toNoteOut(n, previewAs)) });
      }
      if (method === "POST") {
        const previewAs =
          new URL(route.request().url()).searchParams.get("preview_as") ?? "owner";
        postBody = route.request().postDataJSON();
        const id = `n${++nextId}`;
        notes.push({
          id,
          author_id: previewAs,
          title: postBody?.title ?? "",
          // Region note: shape present, no point anchor.
          lng: postBody?.lng ?? null,
          lat: postBody?.lat ?? null,
          shape: postBody?.shape ?? null,
          version: 1,
          sections: (postBody?.sections as StoredSection[]) ?? [],
        });
        return route.fulfill({ status: 201, json: { id } });
      }
      return route.continue();
    });

    await page.goto("/");

    // Map ready.
    await expect(page.locator(".maplibregl-canvas")).toBeVisible();
    await page.waitForFunction(
      () => !!(window as unknown as { __map?: import("maplibre-gl").Map }).__map,
    );

    // Select a non-guest persona so canWrite is true and "Draw circle" appears.
    await page.getByRole("button", { name: "You (owner)" }).click();

    // Start drawing a circle.
    await page.getByRole("button", { name: /draw circle/i }).click();

    // Simulate finishing the circle — the real adapter emits a polygon, so the
    // fake fires a polygon shape too.
    await page.evaluate(
      (c) => (window as unknown as { __emitShape: (c: number[][]) => void }).__emitShape(c),
      RING,
    );

    // The NoteEditor opens in create mode.
    const titleInput = page.getByLabel("Title");
    await expect(titleInput).toBeVisible();

    // Fill the title + the default (Public) section, then save.
    await titleInput.fill("My Drawn Circle Area");
    await page.getByLabel("Section content").first().fill("circle section content");
    await page.getByRole("button", { name: "Save note" }).click();

    // Editor closes.
    await expect(titleInput).not.toBeVisible();

    // PRIMARY assertion: the POST carried the polygon shape end-to-end.
    // A circle is stored as a polygon area note (circle is a one-way drawing tool).
    expect(postBody).not.toBeNull();
    expect(postBody?.shape?.kind).toBe("polygon");
    expect(postBody?.shape?.coordinates).toEqual(RING);
    // Region notes are shape-anchored, not point-anchored.
    expect(postBody).not.toHaveProperty("lng");
    expect(postBody).not.toHaveProperty("lat");

    // SECONDARY assertion: the new region renders via the `regions` source.
    await page.waitForFunction(() => {
      const m = (window as unknown as { __map?: import("maplibre-gl").Map }).__map;
      return !!m && !!m.getSource("regions") && !!m.getLayer("regions-fill");
    });
    await expect
      .poll(
        () =>
          page.evaluate(() => {
            const m = (window as unknown as { __map?: import("maplibre-gl").Map }).__map;
            if (!m) return -1;
            m.triggerRepaint();
            return m.querySourceFeatures("regions").length;
          }),
        { timeout: 10_000 },
      )
      .toBeGreaterThanOrEqual(1);
  });
});
