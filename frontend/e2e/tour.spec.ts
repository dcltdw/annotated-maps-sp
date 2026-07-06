import { expect, test } from "@playwright/test";

const MINIMAL_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#e8e8e8" } }],
};

const MAP = { id: "m1", name: "Greater Boston", lng: -71.0589, lat: 42.3601, zoom: 12 };
const VIEWERS = [
  { id: "rf1", display_name: "A Running Friend", reputation: 10 },
  { id: "df1", display_name: "A Dim Sum Friend", reputation: 10 },
];

const PUBLIC_SECTIONS = [
  { id: "s1", order: 0, visibility: "visible", content: "flat river loop", rule_type: "public", rule_label: "Public" },
];
const FRIEND_SECTIONS = [
  ...PUBLIC_SECTIONS,
  { id: "s2", order: 1, visibility: "visible", content: "start at mass ave", rule_type: "audience", rule_label: "Friends" },
  { id: "s3", order: 2, visibility: "visible", content: "club tempo", rule_type: "audience", rule_label: "Running club" },
];
const LOOP = { id: "n1", title: "Charles River loop", lng: -71.08, lat: 42.359, appends: [], shape: null, editable: false };
const FRIEND_ONLY_PIN = { id: "n2", title: "China Pearl", lng: -71.06, lat: 42.3514, appends: [], shape: null, editable: false, sections: PUBLIC_SECTIONS };

test.describe("demo tour", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/styles/positron**", (r) => r.fulfill({ json: MINIMAL_STYLE }));
    await page.route("**/api/v1/maps", (r) => r.fulfill({ json: [MAP] }));
    await page.route("**/api/v1/maps/*/viewers", (r) => r.fulfill({ json: VIEWERS }));
    await page.route("**/api/v1/maps/*/notes**", (route) => {
      const previewAs = new URL(route.request().url()).searchParams.get("preview_as");
      const loop = { ...LOOP, sections: previewAs === "rf1" ? FRIEND_SECTIONS : PUBLIC_SECTIONS };
      const notes = previewAs === "rf1" ? [loop, FRIEND_ONLY_PIN] : [loop];
      route.fulfill({ json: notes });
    });
  });

  test("auto-starts, performs the switch, opens the showcase, replays via pill", async ({ page }) => {
    await page.goto("/"); // fresh context → no tourSeenV1 → auto-start
    const dialog = page.getByRole("dialog", { name: /guided tour/i });
    await expect(dialog).toBeVisible();

    const next = page.getByRole("button", { name: /next/i });
    await next.click(); // welcome → map (resets persona; one marker as Guest)
    await expect(page.locator(".maplibregl-marker")).toHaveCount(1);
    await next.click(); // map → switcher

    await next.click(); // switcher → switch step: persona flips, pins appear
    await expect(
      page.getByRole("button", { name: "A Running Friend" }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".maplibregl-marker")).toHaveCount(2); // the reveal

    await next.click(); // switch → panel step: showcase note opens
    await expect(page.getByText("Charles River loop")).toBeVisible();
    await expect(page.getByText("club tempo")).toBeVisible();

    await next.click(); // panel → authbar
    await page.getByRole("button", { name: /done/i }).click();
    await expect(dialog).toBeHidden();
    // Finish leaves the visitor ON the rich view (spec: no reset)
    await expect(
      page.getByRole("button", { name: "A Running Friend" }),
    ).toHaveAttribute("aria-pressed", "true");

    // Reload: no auto-start (seen), pill replays
    await page.reload();
    await expect(page.locator(".maplibregl-marker").first()).toBeVisible();
    await expect(page.getByRole("dialog", { name: /guided tour/i })).toBeHidden();
    await page.getByRole("button", { name: /take the tour/i }).click();
    await expect(page.getByRole("dialog", { name: /guided tour/i })).toBeVisible();
  });

  test("degrades by skipping when the showcase note is absent", async ({ page }) => {
    await page.route("**/api/v1/maps/*/notes**", (route) => {
      route.fulfill({ json: [{ ...FRIEND_ONLY_PIN, id: "n9", title: "Some pin" }] });
    });
    await page.goto("/");
    const dialog = page.getByRole("dialog", { name: /guided tour/i });
    await expect(dialog).toBeVisible();
    // Walk the whole tour; it must complete without the panel step crashing anything
    const next = page.getByRole("button", { name: /next|done/i });
    for (let i = 0; i < 6; i++) {
      if (await dialog.isHidden()) break;
      await next.first().click();
    }
    await expect(dialog).toBeHidden();
  });
});
