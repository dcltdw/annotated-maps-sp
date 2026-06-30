import { expect, test } from "@playwright/test";

// ---------------------------------------------------------------------------
// Mid-session token expiry: when an authenticated user's bearer token expires,
// a write fails (the API treats the stale token as a guest → 403). The app
// re-validates via /auth/me; finding the token dead, it drops to anonymous and
// shows a "session expired" prompt instead of leaving the user apparently
// logged in until a manual reload.
// ---------------------------------------------------------------------------

const MINIMAL_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#e8e8e8" } }],
};
const MAP = { id: "m1", name: "Greater Boston", lng: -71.0589, lat: 42.3601, zoom: 13 };
const USER = { id: "u1", display_name: "A Friend", email: "friend@demo.example", reputation: 10 };
const NOTE = {
  id: "n1",
  author_id: "u1",
  title: "My pin",
  lng: -71.0589,
  lat: 42.3601,
  editable: true, // owned by the logged-in user → the delete affordance shows
  shape: null,
  sections: [
    {
      id: "s0",
      order: 0,
      visibility: "visible",
      content: "mine",
      rule_type: "public",
      rule_label: "Public",
      teaser_text: null,
    },
  ],
  appends: [],
};

test("an expired session on a write logs out with a 'session expired' prompt", async ({ page }) => {
  // Start with a restored token so /auth/me (on mount) signs us in.
  await page.addInitScript(() => {
    try {
      localStorage.setItem("authToken", "tok");
    } catch {
      /* ignore */
    }
  });
  await page.route("**/styles/positron**", (r) => r.fulfill({ json: MINIMAL_STYLE }));
  await page.route("**/api/v1/maps", (r) => r.fulfill({ json: [MAP] }));
  await page.route("**/api/v1/maps/*/viewers", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/v1/maps/*/groups", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/v1/maps/*/notes**", (r) =>
    r.request().method() === "GET" ? r.fulfill({ json: [NOTE] }) : r.continue(),
  );

  // /auth/me: the mount call authenticates; afterwards the token is "expired".
  let meCalls = 0;
  await page.route("**/api/v1/auth/me", (r) => {
    meCalls += 1;
    return meCalls === 1 ? r.fulfill({ json: USER }) : r.fulfill({ status: 401, json: {} });
  });
  // The delete write fails the way a guest's would once the token is dead.
  await page.route("**/api/v1/notes/*", (r) =>
    r.request().method() === "DELETE"
      ? r.fulfill({ status: 403, json: { detail: "You can only edit your own notes." } })
      : r.continue(),
  );

  page.on("dialog", (d) => d.accept()); // accept the delete confirm

  await page.goto("/");

  // Signed in: the AuthBar shows "Log out", not "Log in".
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();

  // Select the owned note and delete it — the token is now expired.
  await page.locator(".maplibregl-marker").first().click();
  await page.getByRole("button", { name: "Delete note" }).click();

  // The write 403s, the /auth/me re-check 401s → expiry handling kicks in.
  await expect(page.getByText(/your session expired/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Log in" })).toBeVisible();
  expect(meCalls).toBeGreaterThanOrEqual(2);
});
