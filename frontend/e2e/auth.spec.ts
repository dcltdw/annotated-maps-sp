import { expect, test } from "./fixtures";

// ---------------------------------------------------------------------------
// Shared stubs — mirrors authoring.spec.ts conventions
// ---------------------------------------------------------------------------

const MINIMAL_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#e8e8e8" } }],
};

const MAP = { id: "m1", name: "Greater Boston", lng: -71.0589, lat: 42.3601, zoom: 13 };
const VIEWERS = [
  { id: "owner", display_name: "You (owner)", reputation: 100 },
];
const GROUPS = [{ id: "rc", name: "Running club" }];

const E2E_TOKEN = "e2e-token";
const AUTH_USER = {
  id: "owner",
  email: "owner@demo.example",
  display_name: "You (owner)",
  reputation: 100,
};

// ---------------------------------------------------------------------------
// Types (mirrors authoring.spec.ts)
// ---------------------------------------------------------------------------

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
  lng: number;
  lat: number;
  version: number;
  sections: StoredSection[];
  editable?: boolean;
}

function toNoteOut(n: StoredNote, previewAs: string | null, authUserId: string | null) {
  // Editable if auth user matches author, or (persona-preview mode) previewAs matches.
  const editable =
    n.editable !== undefined
      ? n.editable
      : authUserId === n.author_id || previewAs === n.author_id;
  return {
    id: n.id,
    author_id: n.author_id,
    title: n.title,
    lng: n.lng,
    lat: n.lat,
    editable,
    shape: null,
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

// ---------------------------------------------------------------------------
// Map canvas helpers — same pattern as authoring.spec.ts
// ---------------------------------------------------------------------------

async function clickEmptyMap(
  page: import("@playwright/test").Page,
  x = 200,
  y = 200,
) {
  const canvas = page.locator(".maplibregl-canvas");
  await canvas.evaluate(
    (el, pos) => {
      const rect = el.getBoundingClientRect();
      el.dispatchEvent(
        new MouseEvent("click", {
          bubbles: true,
          cancelable: true,
          clientX: rect.left + pos.x,
          clientY: rect.top + pos.y,
        }),
      );
    },
    { x, y },
  );
}

async function clickMarkerByIndex(
  page: import("@playwright/test").Page,
  idx: number,
) {
  const marker = page.locator(".maplibregl-marker").nth(idx);
  await expect(marker).toBeVisible();
  await marker.evaluate((el) => {
    el.dispatchEvent(new MouseEvent("click", { bubbles: false, cancelable: true }));
  });
}

// ---------------------------------------------------------------------------
// Route wiring with auth stubs
// ---------------------------------------------------------------------------

async function wireAuthRoutes(
  page: import("@playwright/test").Page,
  initialNotes: StoredNote[] = [],
) {
  let nextId = 200;
  const notes: StoredNote[] = [...initialNotes];

  // Capture the last POST /notes request for assertions
  let lastCreateRequest: import("@playwright/test").Request | null = null;

  await page.route("**/styles/positron**", (r) => r.fulfill({ json: MINIMAL_STYLE }));
  await page.route("**/api/v1/maps", (r) => r.fulfill({ json: [MAP] }));
  await page.route("**/api/v1/maps/*/viewers", (r) => r.fulfill({ json: VIEWERS }));
  await page.route("**/api/v1/maps/*/groups", (r) => r.fulfill({ json: GROUPS }));

  // Auth: login
  await page.route("**/api/v1/auth/login", (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({ status: 200, json: { token: E2E_TOKEN, user: AUTH_USER } });
    }
    return route.continue();
  });

  // Auth: me — honor bearer
  await page.route("**/api/v1/auth/me", (route) => {
    const auth = route.request().headers()["authorization"] ?? "";
    if (auth === `Bearer ${E2E_TOKEN}`) {
      return route.fulfill({ status: 200, json: AUTH_USER });
    }
    return route.fulfill({ status: 401, json: { detail: "Unauthorized" } });
  });

  // Auth: logout (best-effort stub)
  await page.route("**/api/v1/auth/logout", (route) => {
    return route.fulfill({ status: 200, json: {} });
  });

  // Notes collection: GET (list) and POST (create)
  await page.route("**/api/v1/maps/*/notes**", (route) => {
    const method = route.request().method();
    if (method === "GET") {
      const url = new URL(route.request().url());
      const previewAs = url.searchParams.get("preview_as") ?? null;
      // For authed requests, determine the viewing user from the bearer token
      const authHeader = route.request().headers()["authorization"] ?? "";
      const authUserId = authHeader === `Bearer ${E2E_TOKEN}` ? AUTH_USER.id : null;
      const topLevel = notes.filter((n) => !("parent" in n));
      return route.fulfill({ json: topLevel.map((n) => toNoteOut(n, previewAs, authUserId)) });
    }
    if (method === "POST") {
      lastCreateRequest = route.request();
      const url = new URL(route.request().url());
      const previewAs = url.searchParams.get("preview_as") ?? null;
      const authHeader = route.request().headers()["authorization"] ?? "";
      const authUserId = authHeader === `Bearer ${E2E_TOKEN}` ? AUTH_USER.id : null;
      // Determine author: authed user takes priority over preview_as
      const authorId = authUserId ?? previewAs ?? "unknown";
      const body = route.request().postDataJSON() as Omit<StoredNote, "id" | "author_id" | "version">;
      const id = `n${++nextId}`;
      const stored: StoredNote = {
        id,
        author_id: authorId,
        title: body.title,
        lng: body.lng,
        lat: body.lat,
        version: 1,
        sections: body.sections as StoredSection[],
        editable: true,
      };
      notes.push(stored);
      return route.fulfill({ status: 201, json: { id } });
    }
    return route.continue();
  });

  // Single-note operations (not needed for create loop, but keeps the stub consistent)
  await page.route("**/api/v1/notes/*", (route) => {
    return route.continue();
  });

  return { notes, getLastCreateRequest: () => lastCreateRequest };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("auth loop (login → bearer-authed create)", () => {
  test("login → authed create note — bearer header sent, no preview_as, note renders", async ({ page }) => {
    await wireAuthRoutes(page);
    await page.goto("/");

    // ---- Step 1: Logged-out state ----
    // The persona switcher ("Viewing as" label) should be visible when logged out
    await expect(page.getByText("Viewing as")).toBeVisible();
    // "Log in" button should be visible
    await expect(page.getByRole("button", { name: /log in/i })).toBeVisible();

    // ---- Step 2: Log in via the popover ----
    // Click the toggle button to open the popover
    await page.getByRole("button", { name: /log in/i }).click();

    // Fill the credentials
    await page.getByLabel(/email/i).fill("owner@demo.example");
    await page.getByLabel(/password/i).fill("demo-pass-12345");

    // Click the submit button — use type=submit to unambiguously target the form
    // submit, not the toggle button (which is type=button).
    await page.locator('button[type="submit"]').click();

    // ---- Step 3: Logged-in state ----
    // Topbar now shows the user's display name
    await expect(page.getByText("You (owner)")).toBeVisible();
    // The persona switcher should be GONE (MapScreen hides it when authUser != null)
    await expect(page.getByText("Viewing as")).not.toBeVisible();

    // ---- Step 4: Create a note as authenticated user ----
    // No markers yet
    await expect(page.locator(".maplibregl-marker")).toHaveCount(0);

    // Click an empty part of the map to open the create editor
    await clickEmptyMap(page, 400, 200);

    // Editor opens
    const titleInput = page.getByLabel("Title");
    await expect(titleInput).toBeVisible();

    // Fill the form
    await titleInput.fill("Authed Note");
    await page.getByLabel("Section content").first().fill("written while logged in");

    // Save — capture the POST request explicitly so the assertion can't race
    // an optimistic-close refactor (editor closing before the 201 arrives).
    const [createReq] = await Promise.all([
      page.waitForRequest(
        (r) => r.method() === "POST" && /\/api\/v1\/maps\/.*\/notes/.test(r.url()),
      ),
      page.getByRole("button", { name: "Save note" }).click(),
    ]);

    // Editor closes
    await expect(titleInput).not.toBeVisible();

    // ---- Step 5: Key assertions on the captured POST request ----
    // (a) The request carried the bearer token
    const authHeader = createReq.headers()["authorization"] ?? "";
    expect(authHeader).toBe(`Bearer ${E2E_TOKEN}`);

    // (b) The URL has NO preview_as query param
    const createUrl = new URL(createReq.url());
    expect(createUrl.searchParams.has("preview_as")).toBe(false);

    // (c) The new note renders — a marker should appear
    await expect(page.locator(".maplibregl-marker")).toHaveCount(1);

    // Click the new marker → panel shows the note title
    await clickMarkerByIndex(page, 0);
    await expect(page.getByText("Authed Note")).toBeVisible();
    await expect(page.getByText("written while logged in")).toBeVisible();
  });
});
