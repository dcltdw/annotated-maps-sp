import { expect, test } from "@playwright/test";

// ---------------------------------------------------------------------------
// Regression guard for the blank-map bug fixed in #25. maplibre adds
// `.maplibregl-map { position: relative }` to our map container at init; our
// `.map-wrap > .map { position: absolute; inset: 0 }` must out-specify it so the
// container fills its wrapper instead of collapsing to height 0. That conflict
// only surfaces in the BUILT/concatenated CSS (source order), not the dev
// server's injected order — so this runs against `vite preview`, not `vite dev`.
// ---------------------------------------------------------------------------

const MINIMAL_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#e8e8e8" } }],
};
const MAP = { id: "m1", name: "Greater Boston", lng: -71.0589, lat: 42.3601, zoom: 13 };

test("the production-built map container fills its wrapper (does not collapse to height 0)", async ({
  page,
}) => {
  await page.route("**/styles/positron**", (r) => r.fulfill({ json: MINIMAL_STYLE }));
  await page.route("**/api/v1/maps", (r) => r.fulfill({ json: [MAP] }));
  await page.route("**/api/v1/maps/*/viewers", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/v1/maps/*/groups", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/v1/maps/*/notes**", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ status: 401, json: {} }));

  await page.goto("/");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();

  const probe = await page.evaluate(() => {
    const el = document.querySelector<HTMLElement>(".map");
    if (!el) return null;
    const cs = getComputedStyle(el);
    return { position: cs.position, height: Math.round(el.getBoundingClientRect().height) };
  });

  expect(probe).not.toBeNull();
  expect(probe!.position).toBe("absolute"); // not maplibre's overriding "relative"
  expect(probe!.height).toBeGreaterThan(200); // a filled container, not collapsed to 0
});
