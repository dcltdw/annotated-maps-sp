import { expect, test } from "@playwright/test";

// ---------------------------------------------------------------------------
// The API is on free hosting that spins down when idle, so the first /maps after
// a gap can fail transiently. The initial load retries with backoff and shows a
// "waking up" message, then recovers WITHOUT a manual reload.
// ---------------------------------------------------------------------------

const MINIMAL_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#e8e8e8" } }],
};
const MAP = { id: "m1", name: "Greater Boston", lng: -71.0589, lat: 42.3601, zoom: 13 };

test("transient /maps failures show 'waking up' then self-heal to a rendered map", async ({
  page,
}) => {
  await page.route("**/styles/positron**", (r) => r.fulfill({ json: MINIMAL_STYLE }));

  let mapsCalls = 0;
  await page.route("**/api/v1/maps", (r) => {
    if (r.request().method() !== "GET") return r.continue();
    mapsCalls += 1;
    // Fail the first two attempts (like a backend still spinning up), then succeed.
    if (mapsCalls <= 2) return r.fulfill({ status: 503, json: {} });
    return r.fulfill({ json: [MAP] });
  });
  await page.route("**/api/v1/maps/*/viewers", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/v1/maps/*/groups", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/v1/maps/*/notes**", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ status: 401, json: {} }));

  await page.goto("/");

  // While retrying, the waking-up message is shown (not the scary error).
  await expect(page.getByText(/waking up the demo server/i)).toBeVisible();

  // Without any reload, the retry succeeds and the map renders.
  await expect(page.locator(".maplibregl-canvas")).toBeVisible({ timeout: 15_000 });
  expect(mapsCalls).toBeGreaterThanOrEqual(3);
});
