import { test, expect } from "@playwright/test";

// Live-deployment smoke: proves the full chain (ALB → web pod → API pods →
// database) serves the real app. Screenshots are the pipeline's evidence.
//
// API_BASE_URL: optional override for the health-check request's target origin.
// The AWS pipeline's Ingress path-routes /api to the backend Service on the SAME
// host as the frontend (deploy/helm/annotated-maps/templates/ingress.yaml), so
// it's unset there and the request below resolves relative to BASE_URL as written.
// The public Render demo used to verify this suite locally instead splits the
// frontend and API across two separate hostnames (annotated-maps-web vs
// annotated-maps-api), so verifying against it sets this to the API's own origin.
const API_ORIGIN = process.env.API_BASE_URL ?? "";

test("API health answers through the ALB", async ({ request }) => {
  const res = await request.get(`${API_ORIGIN}/api/v1/health`);
  expect(res.status()).toBe(200);
});

test("the app renders the seeded map", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Annotated Maps/i);
  // The persona switcher only renders once the app has data from the API.
  await expect(page.getByText("Viewing as")).toBeVisible({ timeout: 30_000 });

  // Wait for a MARKER, not the canvas. The canvas exists the instant maplibre
  // initialises, so asserting on it passes against a completely blank map —
  // the first pipeline run screenshotted exactly that and still went green.
  // A marker only appears after the basemap style has loaded AND the API's
  // seeded notes arrived, so it is the assertion that actually proves the
  // chain (ALB → web → API → database → render) end to end.
  //
  // Unlike the local suite (which stubs the style to avoid OpenFreeMap), this
  // runs against a real deployment and fetches the real style, so allow for a
  // cold external fetch.
  const markers = page.locator(".maplibregl-marker");
  await expect(markers.first()).toBeVisible({ timeout: 60_000 });
  expect(await markers.count()).toBeGreaterThan(0);

  // Only now is the screenshot worth keeping as evidence.
  await page.screenshot({ path: "test-results/alb-smoke-app.png", fullPage: true });
});

test("personas are present", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Run-club Member" })).toBeVisible({
    timeout: 30_000,
  });
});
