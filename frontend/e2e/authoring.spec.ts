import { expect, test } from "@playwright/test";

// ---------------------------------------------------------------------------
// Shared stubs
// ---------------------------------------------------------------------------

const MINIMAL_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#e8e8e8" } }],
};

const MAP = { id: "m1", name: "Greater Boston", lng: -71.0589, lat: 42.3601, zoom: 13 };
const VIEWERS = [
  { id: "owner", display_name: "You (owner)", reputation: 100 },
  { id: "friend", display_name: "A Friend", reputation: 10 },
];
const GROUPS = [{ id: "rc", name: "Running club" }];

// ---------------------------------------------------------------------------
// Shape helpers
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
}

function ruleLabel(s: StoredSection): string {
  if (s.rule_type === "public") return "Public";
  if (s.rule_type === "audience") return "Audience";
  if (s.rule_type === "attribute_gate") return `Reputation ≥ ${s.rule_params.threshold ?? 50}`;
  return "Private";
}

// The author-loop suite renders every section as fully visible (visibility "visible",
// teaser_text null) — it exercises create/edit/delete of OWNED content, not the
// visibility slicing (that's covered by viewing-as.spec.ts). Extend this helper if a
// future authoring test needs teaser/locked sections.
function toNoteOut(n: StoredNote) {
  return {
    id: n.id,
    author_id: n.author_id,
    title: n.title,
    lng: n.lng,
    lat: n.lat,
    sections: n.sections.map((s, i) => ({
      id: `${n.id}-s${i}`,
      order: s.order,
      visibility: "visible" as const,
      content: s.content,
      rule_type: s.rule_type,
      rule_label: ruleLabel(s),
      teaser_text: null,
    })),
  };
}

function toNoteEdit(n: StoredNote) {
  return {
    id: n.id,
    title: n.title,
    lng: n.lng,
    lat: n.lat,
    version: n.version,
    sections: n.sections.map((s) => ({
      order: s.order,
      content: s.content,
      rule_type: s.rule_type,
      rule_params: s.rule_params,
      teaser: s.teaser,
      teaser_text: s.teaser_text,
    })),
  };
}

// ---------------------------------------------------------------------------
// Route-wiring helper — sets up all stateful routes for a single test.
// Returns the mutable `notes` array so each test can seed or inspect it.
// ---------------------------------------------------------------------------

async function wireRoutes(
  page: import("@playwright/test").Page,
  initialNotes: StoredNote[] = [],
) {
  let nextId = 100;
  const notes: StoredNote[] = [...initialNotes];

  await page.route("**/styles/positron**", (r) => r.fulfill({ json: MINIMAL_STYLE }));
  await page.route("**/api/v1/maps", (r) => r.fulfill({ json: [MAP] }));
  await page.route("**/api/v1/maps/*/viewers", (r) => r.fulfill({ json: VIEWERS }));
  await page.route("**/api/v1/maps/*/groups", (r) => r.fulfill({ json: GROUPS }));

  // notes collection: GET (list) and POST (create)
  await page.route("**/api/v1/maps/*/notes**", (route) => {
    const method = route.request().method();
    if (method === "GET") {
      return route.fulfill({ json: notes.map(toNoteOut) });
    }
    if (method === "POST") {
      const previewAs =
        new URL(route.request().url()).searchParams.get("preview_as") ?? "unknown";
      const body = route.request().postDataJSON() as Omit<StoredNote, "id" | "author_id" | "version">;
      const id = `n${++nextId}`;
      const stored: StoredNote = {
        id,
        author_id: previewAs,
        title: body.title,
        lng: body.lng,
        lat: body.lat,
        version: 1,
        sections: body.sections as StoredSection[],
      };
      notes.push(stored);
      return route.fulfill({ status: 201, json: { id } });
    }
    return route.continue();
  });

  // single-note edit shape: GET /api/v1/notes/:id/edit
  await page.route("**/api/v1/notes/*/edit**", (route) => {
    const parts = route.request().url().split("/");
    const noteId = parts[parts.indexOf("notes") + 1];
    const found = notes.find((n) => n.id === noteId);
    if (!found) return route.fulfill({ status: 404, json: { detail: "not found" } });
    return route.fulfill({ json: toNoteEdit(found) });
  });

  // single-note: PUT (update) and DELETE
  await page.route("**/api/v1/notes/*", (route) => {
    const method = route.request().method();
    const parts = route.request().url().split("/");
    // strip query string from the last segment
    const noteId = parts[parts.indexOf("notes") + 1].split("?")[0];

    if (method === "PUT") {
      const body = route.request().postDataJSON() as StoredNote & { version: number };
      const idx = notes.findIndex((n) => n.id === noteId);
      if (idx === -1) return route.fulfill({ status: 404, json: { detail: "not found" } });
      const updated: StoredNote = {
        ...notes[idx],
        title: body.title,
        lng: body.lng,
        lat: body.lat,
        sections: body.sections as StoredSection[],
        version: (notes[idx].version ?? 1) + 1,
      };
      notes[idx] = updated;
      return route.fulfill({ json: { id: noteId, version: updated.version } });
    }

    if (method === "DELETE") {
      const idx = notes.findIndex((n) => n.id === noteId);
      if (idx !== -1) notes.splice(idx, 1);
      return route.fulfill({ status: 204, body: "" });
    }

    return route.continue();
  });

  return notes;
}

// ---------------------------------------------------------------------------
// Helper: click a marker by dispatching a native click with bubbles:false.
//
// Playwright's actionability check misfires on maplibre markers under headless
// WebGL (overlay intercepts), so we use evaluate. We pass bubbles:false so the
// synthetic click does NOT propagate up to the maplibre canvas event listener —
// otherwise when canWrite is true the map's "click" handler also fires,
// opening the create-note editor instead of selecting the note.
// ---------------------------------------------------------------------------

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
// Helper: click an empty spot on the map canvas to trigger the create-note flow.
// Uses dispatchEvent on the canvas to avoid the pointer-intercept check that
// prevents .click({position}) from landing when the map-wrap div is on top.
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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("author loop (stateful stub)", () => {
  // -------------------------------------------------------------------------
  // 1. Create
  // -------------------------------------------------------------------------
  test("create note — POST reflected in new marker and panel", async ({ page }) => {
    await wireRoutes(page); // start with no notes
    await page.goto("/");

    // no markers yet
    await expect(page.locator(".maplibregl-marker")).toHaveCount(0);

    // switch to owner persona
    await page.getByRole("button", { name: "You (owner)" }).click();

    // click an empty part of the map canvas
    await clickEmptyMap(page, 400, 200);

    // editor opens
    const titleInput = page.getByLabel("Title");
    await expect(titleInput).toBeVisible();

    // fill section 1 (already exists, defaults to Public)
    await titleInput.fill("My New Note");
    await page.getByLabel("Section content").first().fill("first section content");

    // add section 2
    await page.getByRole("button", { name: "＋ Add section" }).click();

    // second textarea — click Audience rule on section 2
    // Scope to the second <li class="ed-section"> to disambiguate from section 1's buttons.
    const section2 = page.locator("li.ed-section").nth(1);
    await section2.getByRole("button", { name: "Audience" }).click();
    // pick the Running club group
    await section2.getByRole("button", { name: "Running club" }).click();
    await section2.getByLabel("Section content").fill("audience-only content");

    // save
    await page.getByRole("button", { name: "Save note" }).click();

    // editor closes, a marker appears
    await expect(titleInput).not.toBeVisible();
    await expect(page.locator(".maplibregl-marker")).toHaveCount(1);

    // click the new marker → panel shows both sections' content
    await clickMarkerByIndex(page, 0);
    await expect(page.getByText("My New Note")).toBeVisible();
    await expect(page.getByText("first section content")).toBeVisible();
    await expect(page.getByText("audience-only content")).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // 2. Edit own note
  // -------------------------------------------------------------------------
  test("edit own note — title updated in panel", async ({ page }) => {
    const seeded: StoredNote = {
      id: "n1",
      author_id: "owner",
      title: "Original Title",
      lng: -71.0589,
      lat: 42.3601,
      version: 1,
      sections: [
        {
          order: 0,
          content: "some content",
          rule_type: "public",
          rule_params: {},
          teaser: false,
          teaser_text: "",
        },
      ],
    };
    await wireRoutes(page, [seeded]);
    await page.goto("/");

    // marker for the seeded note
    await expect(page.locator(".maplibregl-marker")).toHaveCount(1);

    // switch to owner
    await page.getByRole("button", { name: "You (owner)" }).click();

    // click the marker → panel
    await clickMarkerByIndex(page, 0);
    await expect(page.getByText("Original Title")).toBeVisible();

    // open editor
    await page.getByRole("button", { name: "Edit note" }).click();

    // editor pre-filled
    const titleInput = page.getByLabel("Title");
    await expect(titleInput).toHaveValue("Original Title");

    // change the title
    await titleInput.fill("Updated Title");
    await page.getByRole("button", { name: "Save note" }).click();

    // Editor closes; the panel auto-reopens for the still-selected note and
    // reactively reflects the reloaded title (the assertion auto-retries until the
    // post-save notes reload lands — no manual re-click / wait needed).
    await expect(titleInput).not.toBeVisible();
    await expect(page.getByText("Updated Title")).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // 3. Version conflict
  // -------------------------------------------------------------------------
  test("version conflict — shows conflict message", async ({ page }) => {
    const seeded: StoredNote = {
      id: "n1",
      author_id: "owner",
      title: "Conflicted Note",
      lng: -71.0589,
      lat: 42.3601,
      version: 1,
      sections: [
        {
          order: 0,
          content: "content",
          rule_type: "public",
          rule_params: {},
          teaser: false,
          teaser_text: "",
        },
      ],
    };
    await wireRoutes(page, [seeded]);
    await page.goto("/");

    await page.getByRole("button", { name: "You (owner)" }).click();
    await clickMarkerByIndex(page, 0);
    await page.getByRole("button", { name: "Edit note" }).click();

    // Override the PUT route to return 409 AFTER the base route (last registered wins)
    await page.route("**/api/v1/notes/*", (route) => {
      if (route.request().method() === "PUT") {
        return route.fulfill({ status: 409, json: { detail: "conflict" } });
      }
      return route.continue();
    });

    await page.getByRole("button", { name: "Save note" }).click();

    // conflict message appears
    await expect(
      page.getByText("This note was changed elsewhere — reload and try again."),
    ).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // 4. Delete own note
  // -------------------------------------------------------------------------
  test("delete own note — marker disappears", async ({ page }) => {
    const seeded: StoredNote = {
      id: "n1",
      author_id: "owner",
      title: "To Be Deleted",
      lng: -71.0589,
      lat: 42.3601,
      version: 1,
      sections: [
        {
          order: 0,
          content: "content",
          rule_type: "public",
          rule_params: {},
          teaser: false,
          teaser_text: "",
        },
      ],
    };
    await wireRoutes(page, [seeded]);
    await page.goto("/");

    await page.getByRole("button", { name: "You (owner)" }).click();
    await expect(page.locator(".maplibregl-marker")).toHaveCount(1);

    await clickMarkerByIndex(page, 0);
    await expect(page.getByText("To Be Deleted")).toBeVisible();

    // accept the window.confirm that delete triggers
    page.on("dialog", (d) => d.accept());
    await page.getByRole("button", { name: "Delete note" }).click();

    // marker gone, title gone
    await expect(page.locator(".maplibregl-marker")).toHaveCount(0);
    await expect(page.getByText("To Be Deleted")).not.toBeVisible();
  });

  // -------------------------------------------------------------------------
  // 5. Guest read-only
  // -------------------------------------------------------------------------
  test("guest — no editor on map click, no edit/delete buttons on panel", async ({ page }) => {
    const seeded: StoredNote = {
      id: "n1",
      author_id: "owner",
      title: "Guest View Note",
      lng: -71.0589,
      lat: 42.3601,
      version: 1,
      sections: [
        {
          order: 0,
          content: "visible to guest",
          rule_type: "public",
          rule_params: {},
          teaser: false,
          teaser_text: "",
        },
      ],
    };
    await wireRoutes(page, [seeded]);
    await page.goto("/");

    // no persona switch — remain Guest

    // click empty map: no editor should appear
    await clickEmptyMap(page, 400, 200);
    await expect(page.getByLabel("Title")).not.toBeVisible();

    // click note marker → panel visible but no edit/delete affordances
    await clickMarkerByIndex(page, 0);
    await expect(page.getByText("Guest View Note")).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit note" })).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Delete note" })).not.toBeVisible();
  });

  // -------------------------------------------------------------------------
  // 6. Non-author read-only
  // -------------------------------------------------------------------------
  test("non-author — panel shows note but no edit/delete buttons", async ({ page }) => {
    // note authored by "friend"; owner views it — owner !== author_id
    const seeded: StoredNote = {
      id: "n2",
      author_id: "friend",
      title: "Friend's Note",
      lng: -71.0589,
      lat: 42.3601,
      version: 1,
      sections: [
        {
          order: 0,
          content: "friend content",
          rule_type: "public",
          rule_params: {},
          teaser: false,
          teaser_text: "",
        },
      ],
    };
    await wireRoutes(page, [seeded]);
    await page.goto("/");

    // switch to owner persona
    await page.getByRole("button", { name: "You (owner)" }).click();

    // click the note (authored by friend)
    await clickMarkerByIndex(page, 0);
    await expect(page.getByText("Friend's Note")).toBeVisible();

    // owner is NOT the author — no edit/delete affordances
    await expect(page.getByRole("button", { name: "Edit note" })).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Delete note" })).not.toBeVisible();
  });
});
