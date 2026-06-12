import { expect, test } from "@playwright/test";

// A minimal valid maplibre style so the map loads without hitting OpenFreeMap.
const MINIMAL_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#e8e8e8" } }],
};

const MAP = { id: "m1", name: "Greater Boston", lng: -71.0589, lat: 42.3601, zoom: 12 };
const VIEWERS = [{ id: "owner", display_name: "You (owner)", reputation: 100 }];

const GUEST = [
  { id: "s1", order: 0, visibility: "visible", content: "scenic loop", rule_type: "public", rule_label: "Public" },
  { id: "s2", order: 1, visibility: "teaser", content: null, rule_type: "audience", rule_label: "Running club" },
];
const OWNER = [
  { id: "s1", order: 0, visibility: "visible", content: "scenic loop", rule_type: "public", rule_label: "Public" },
  { id: "s2", order: 1, visibility: "visible", content: "club fountain", rule_type: "audience", rule_label: "Running club" },
  { id: "s3", order: 2, visibility: "visible", content: "trusted tip", rule_type: "attribute_gate", rule_label: "Reputation ≥ 50" },
  { id: "s4", order: 3, visibility: "visible", content: "knee reminder", rule_type: "private", rule_label: "Private" },
];
const note = (sections: unknown[]) => [{ id: "n1", title: "Castle Island", lng: -71.0136, lat: 42.338, sections }];

test("the Viewing-as switcher re-filters a note's sections live", async ({ page }) => {
  await page.route("**/styles/positron**", (r) => r.fulfill({ json: MINIMAL_STYLE }));
  await page.route("**/api/v1/maps", (r) => r.fulfill({ json: [MAP] }));
  await page.route("**/api/v1/maps/*/viewers", (r) => r.fulfill({ json: VIEWERS }));
  await page.route("**/api/v1/maps/*/notes**", (route) => {
    const previewAs = new URL(route.request().url()).searchParams.get("preview_as");
    route.fulfill({ json: note(previewAs ? OWNER : GUEST) });
  });

  await page.goto("/");

  // real maplibre places a marker once the (stubbed) style loads
  const marker = page.locator(".maplibregl-marker").first();
  await expect(marker).toBeVisible();
  // The marker's click listener is on the DOM element directly; use dispatchEvent so the
  // native event fires regardless of any overlay interception.
  await marker.dispatchEvent("click");

  // Guest: Public visible, Running-club locked, gate/private absent
  await expect(page.getByText("scenic loop")).toBeVisible();
  await expect(page.getByText(/Locked/i)).toBeVisible();
  await expect(page.getByText(/Reputation ≥ 50/)).toHaveCount(0);

  // Switch persona → backend (stub) returns the owner slice → panel re-renders live
  await page.getByRole("button", { name: "You (owner)" }).click();
  await expect(page.getByText(/Reputation ≥ 50/)).toBeVisible();
  await expect(page.getByText("Private")).toBeVisible();
  await expect(page.getByText("club fountain")).toBeVisible();
});
