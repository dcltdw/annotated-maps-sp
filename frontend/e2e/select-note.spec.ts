import { expect, test } from "@playwright/test";

// ---------------------------------------------------------------------------
// Regression: clicking an existing note must SELECT it (open the detail panel),
// not drop a new pin — even when the viewer can write (a persona is selected).
// The map's general click handler creates a pin; a click on a marker or a
// region/route feature must not also trigger it.
// ---------------------------------------------------------------------------

const MINIMAL_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#e8e8e8" } }],
};

const MAP = { id: "m1", name: "Greater Boston", lng: -71.0589, lat: 42.3601, zoom: 13 };
const VIEWERS = [{ id: "owner", display_name: "You (owner)", reputation: 100 }];

const PIN_NOTE = {
  id: "pin1",
  author_id: "someone",
  title: "China Pearl",
  lng: -71.0589,
  lat: 42.3601,
  editable: false,
  shape: null,
  sections: [
    {
      id: "pin1-s0",
      order: 0,
      visibility: "visible",
      content: "Favorite dim sum place.",
      rule_type: "public",
      rule_label: "Public",
      teaser_text: null,
    },
  ],
  appends: [],
};

const POLYGON_NOTE = {
  id: "area1",
  author_id: "someone",
  title: "Public Garden",
  lng: null,
  lat: null,
  editable: false,
  shape: {
    kind: "polygon",
    coordinates: [
      [-71.055, 42.355],
      [-71.05, 42.355],
      [-71.05, 42.35],
      [-71.055, 42.35],
      [-71.055, 42.355],
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

async function wireRoutes(page: import("@playwright/test").Page) {
  await page.route("**/styles/positron**", (r) => r.fulfill({ json: MINIMAL_STYLE }));
  await page.route("**/api/v1/maps", (r) => r.fulfill({ json: [MAP] }));
  await page.route("**/api/v1/maps/*/viewers", (r) => r.fulfill({ json: VIEWERS }));
  await page.route("**/api/v1/maps/*/groups", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/v1/maps/*/notes**", (route) => {
    if (route.request().method() !== "GET") return route.continue();
    return route.fulfill({ json: [PIN_NOTE, POLYGON_NOTE] });
  });
}

test.describe("clicking an existing note selects it (does not create a pin)", () => {
  test("marker click opens the detail panel, not the New Pin editor", async ({ page }) => {
    await wireRoutes(page);
    await page.goto("/");
    await expect(page.locator(".maplibregl-canvas")).toBeVisible();

    // Become a writer so the map's click-to-create path is armed.
    await page.getByRole("button", { name: "You (owner)" }).click();

    await page.locator(".maplibregl-marker").first().click();

    await expect(page.locator(".note-panel")).toBeVisible();
    await expect(page.locator(".note-panel")).toContainText("China Pearl");
    await expect(page.locator(".note-editor")).toHaveCount(0);
  });

  test("region click opens the detail panel, not the New Pin editor", async ({ page }) => {
    await wireRoutes(page);
    await page.goto("/");
    await expect(page.locator(".maplibregl-canvas")).toBeVisible();
    await page.getByRole("button", { name: "You (owner)" }).click();

    await page.waitForFunction(() => {
      const m = (window as unknown as { __map?: import("maplibre-gl").Map }).__map;
      return !!m && !!m.getLayer("regions-fill");
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

    const pt = await page.evaluate(() => {
      const m = (window as unknown as { __map?: import("maplibre-gl").Map }).__map!;
      const p = m.project([-71.0525, 42.3525]); // interior of POLYGON_NOTE
      const c = m.getCanvas().getBoundingClientRect();
      return { x: c.left + p.x, y: c.top + p.y };
    });
    await page.mouse.click(pt.x, pt.y);

    await expect(page.locator(".note-panel")).toBeVisible();
    await expect(page.locator(".note-panel")).toContainText("Public Garden");
    await expect(page.locator(".note-editor")).toHaveCount(0);
  });
});
