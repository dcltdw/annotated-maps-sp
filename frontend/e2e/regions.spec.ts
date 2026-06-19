import { expect, test } from "@playwright/test";

// ---------------------------------------------------------------------------
// Region read-path e2e: stub the notes endpoint with one polygon (area) note
// and one line (path) note, load the app over real maplibre, and assert the
// `regions` source/layers render their features on the map.
// ---------------------------------------------------------------------------

const MINIMAL_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#e8e8e8" } }],
};

const MAP = { id: "m1", name: "Greater Boston", lng: -71.0589, lat: 42.3601, zoom: 13 };
const VIEWERS = [{ id: "owner", display_name: "You (owner)", reputation: 100 }];
const GROUPS = [{ id: "rc", name: "Running club" }];

// A polygon note (area) and a line note (path). Each carries a populated `shape`,
// one visible public section, editable:false, and no appends.
const POLYGON_NOTE = {
  id: "area1",
  author_id: "owner",
  title: "Public Garden",
  lng: null,
  lat: null,
  editable: false,
  shape: {
    kind: "polygon",
    coordinates: [
      [-71.0710, 42.3540],
      [-71.0690, 42.3540],
      [-71.0690, 42.3525],
      [-71.0710, 42.3525],
      [-71.0710, 42.3540],
    ],
  },
  sections: [
    {
      id: "area1-s0",
      order: 0,
      visibility: "visible",
      content: "A lovely public garden.",
      rule_type: "public",
      rule_label: "Public",
      teaser_text: null,
    },
  ],
  appends: [],
};

const LINE_NOTE = {
  id: "path1",
  author_id: "owner",
  title: "Esplanade route",
  lng: null,
  lat: null,
  editable: false,
  shape: {
    kind: "line",
    coordinates: [
      [-71.0750, 42.3560],
      [-71.0700, 42.3580],
      [-71.0650, 42.3600],
    ],
  },
  sections: [
    {
      id: "path1-s0",
      order: 0,
      visibility: "visible",
      content: "Scenic riverside run.",
      rule_type: "public",
      rule_label: "Public",
      teaser_text: null,
    },
  ],
  appends: [],
};

async function wireRoutes(page: import("@playwright/test").Page) {
  await page.route("**/styles/positron**", (r) => r.fulfill({ json: MINIMAL_STYLE }));
  await page.route("**/api/v1/maps", (r) => r.fulfill({ json: [MAP] }));
  await page.route("**/api/v1/maps/*/viewers", (r) => r.fulfill({ json: VIEWERS }));
  await page.route("**/api/v1/maps/*/groups", (r) => r.fulfill({ json: GROUPS }));
  await page.route("**/api/v1/maps/*/notes**", (route) => {
    if (route.request().method() !== "GET") return route.continue();
    return route.fulfill({ json: [POLYGON_NOTE, LINE_NOTE] });
  });
}

test.describe("region read path", () => {
  test("renders polygon + line region features on the map", async ({ page }) => {
    await wireRoutes(page);
    await page.goto("/");

    // Map mounts and exposes itself.
    await expect(page.locator(".maplibregl-canvas")).toBeVisible();
    await page.waitForFunction(
      () => !!(window as unknown as { __map?: import("maplibre-gl").Map }).__map,
    );

    // Wait for the regions source + both layers to be added (style load + notes effect).
    await page.waitForFunction(() => {
      const m = (window as unknown as { __map?: import("maplibre-gl").Map }).__map;
      return !!m && !!m.getSource("regions") && !!m.getLayer("regions-fill") && !!m.getLayer("regions-line");
    });

    // Assert the rendered region features. querySourceFeatures only returns features
    // once a render pass has populated the source's tile cache, so poll (forcing a
    // repaint each tick) until both region features show up.
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
      .toBeGreaterThanOrEqual(2);
  });
});
