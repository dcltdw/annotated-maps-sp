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
  // appends are also stored as StoredNote entries with parent set
  parent?: string;
}

function ruleLabel(s: StoredSection): string {
  if (s.rule_type === "public") return "Public";
  if (s.rule_type === "audience") return "Audience";
  if (s.rule_type === "attribute_gate") return `Reputation ≥ ${s.rule_params.threshold ?? 50}`;
  return "Private";
}

function authorName(authorId: string): string {
  return VIEWERS.find((v) => v.id === authorId)?.display_name ?? authorId;
}

// Build AppendOut from a stored append note, visibility-filtering sections by previewAs.
// A Private section is only visible to the append's own author — this mirrors the backend's
// per-append owner filtering (each append uses ITS OWN author as the owner for visibility).
function toAppendOut(ap: StoredNote, previewAs: string | null) {
  return {
    id: ap.id,
    author_id: ap.author_id,
    author_name: authorName(ap.author_id),
    title: ap.title ?? "",
    // Mirrors the backend's non-sandbox `editable` (author == preview_as).
    editable: previewAs === ap.author_id,
    sections: ap.sections
      .filter((s) => {
        if (s.rule_type === "private") {
          // Private: only visible if viewer IS the append's author
          return previewAs === ap.author_id;
        }
        // Public (and others) always visible in this test model
        return true;
      })
      .map((s, i) => ({
        id: `${ap.id}-s${i}`,
        order: s.order,
        visibility: "visible" as const,
        content: s.content,
        rule_type: s.rule_type,
        rule_label: ruleLabel(s),
        teaser_text: null,
      })),
  };
}

// The author-loop suite renders every section as fully visible (visibility "visible",
// teaser_text null) — it exercises create/edit/delete of OWNED content, not the
// visibility slicing (that's covered by viewing-as.spec.ts). Extend this helper if a
// future authoring test needs teaser/locked sections.
function toNoteOut(n: StoredNote, allNotes: StoredNote[], previewAs: string | null) {
  const appends = allNotes
    .filter((a) => a.parent === n.id)
    .map((a) => toAppendOut(a, previewAs));
  return {
    id: n.id,
    author_id: n.author_id,
    title: n.title,
    lng: n.lng,
    lat: n.lat,
    // Mirrors the backend's non-sandbox `editable` (author == preview_as).
    editable: previewAs === n.author_id,
    sections: n.sections.map((s, i) => ({
      id: `${n.id}-s${i}`,
      order: s.order,
      visibility: "visible" as const,
      content: s.content,
      rule_type: s.rule_type,
      rule_label: ruleLabel(s),
      teaser_text: null,
    })),
    appends,
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
  // Note: GET /maps/*/notes also handles ?preview_as= query strings via glob **
  await page.route("**/api/v1/maps/*/notes**", (route) => {
    const method = route.request().method();
    if (method === "GET") {
      const previewAs =
        new URL(route.request().url()).searchParams.get("preview_as") ?? null;
      // Only return top-level notes (parent === undefined)
      const topLevel = notes.filter((n) => n.parent == null);
      return route.fulfill({ json: topLevel.map((n) => toNoteOut(n, notes, previewAs)) });
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

  // append create: POST /api/v1/notes/:id/appends.
  // The /notes/* catch-all (registered later, so higher precedence in Playwright's
  // last-registered-wins stack) also matches this URL, but it route.continue()s on
  // POST — so the request falls through to this handler. Order works either way here.
  await page.route("**/api/v1/notes/*/appends**", (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const parts = route.request().url().split("/");
    const notesIdx = parts.lastIndexOf("notes");
    const parentId = parts[notesIdx + 1].split("?")[0];
    const previewAs =
      new URL(route.request().url()).searchParams.get("preview_as") ?? "unknown";
    const body = route.request().postDataJSON() as { title: string; sections: StoredSection[] };
    const id = `ap${++nextId}`;
    const stored: StoredNote = {
      id,
      parent: parentId,
      author_id: previewAs,
      title: body.title ?? "",
      lng: 0,
      lat: 0,
      version: 1,
      sections: body.sections as StoredSection[],
    };
    notes.push(stored);
    return route.fulfill({ status: 201, json: { id } });
  });

  // append update: PUT /api/v1/appends/:id
  await page.route("**/api/v1/appends/*", (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    const parts = route.request().url().split("/");
    const appendId = parts[parts.indexOf("appends") + 1].split("?")[0];
    const body = route.request().postDataJSON() as { title: string; sections: StoredSection[]; version: number };
    const idx = notes.findIndex((n) => n.id === appendId);
    if (idx === -1) return route.fulfill({ status: 404, json: { detail: "not found" } });
    const updated: StoredNote = {
      ...notes[idx],
      title: body.title ?? "",
      sections: body.sections as StoredSection[],
      version: (notes[idx].version ?? 1) + 1,
    };
    notes[idx] = updated;
    return route.fulfill({ json: { id: appendId, version: updated.version } });
  });

  // single-note edit shape: GET /api/v1/notes/:id/edit.
  // The /notes/* catch-all below also matches this URL but route.continue()s on GET,
  // so the request falls through to this GET handler.
  await page.route("**/api/v1/notes/*/edit**", (route) => {
    const parts = route.request().url().split("/");
    const noteId = parts[parts.indexOf("notes") + 1];
    const found = notes.find((n) => n.id === noteId);
    if (!found) return route.fulfill({ status: 404, json: { detail: "not found" } });
    return route.fulfill({ json: toNoteEdit(found) });
  });

  // single-note: PUT (update) and DELETE
  // Works for both notes and appends since appends are stored in the same `notes` array.
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

  // -------------------------------------------------------------------------
  // 7. Append — create via ＋Append → appears inline under note
  // -------------------------------------------------------------------------
  test("append — create via UI appears inline with author name", async ({ page }) => {
    const parentNote: StoredNote = {
      id: "n1",
      author_id: "friend",
      title: "Parent Note",
      lng: -71.0589,
      lat: 42.3601,
      version: 1,
      sections: [
        {
          order: 0,
          content: "parent content",
          rule_type: "public",
          rule_params: {},
          teaser: false,
          teaser_text: "",
        },
      ],
    };
    await wireRoutes(page, [parentNote]);
    await page.goto("/");

    // Switch to owner persona (any non-guest can append)
    await page.getByRole("button", { name: "You (owner)" }).click();

    // Click the parent note marker
    await clickMarkerByIndex(page, 0);
    await expect(page.getByText("Parent Note")).toBeVisible();

    // Open the append editor
    await page.getByRole("button", { name: /append to this note/i }).click();

    // The append editor should open (header contains "New append")
    await expect(page.getByText(/new append/i)).toBeVisible();

    // Add a public section (section textarea is already present)
    await page.getByLabel("Section content").fill("My append content");

    // Save the append
    await page.getByRole("button", { name: /save append/i }).click();

    // Editor closes
    await expect(page.getByText(/new append/i)).not.toBeVisible();

    // The append appears inline under the note with the author's display name.
    // Scope to the .who span inside the appends area to avoid ambiguity with the
    // persona button and panel header that also contain "You (owner)".
    await expect(page.locator(".append .who").getByText("You (owner)")).toBeVisible();
    await expect(page.getByText("My append content")).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // 8. Edit own append — change content reflected inline
  // -------------------------------------------------------------------------
  test("edit own append — updated content reflected inline", async ({ page }) => {
    const parentNote: StoredNote = {
      id: "n1",
      author_id: "friend",
      title: "Parent Note",
      lng: -71.0589,
      lat: 42.3601,
      version: 1,
      sections: [
        {
          order: 0,
          content: "parent content",
          rule_type: "public",
          rule_params: {},
          teaser: false,
          teaser_text: "",
        },
      ],
    };
    // Seed an existing append by owner
    const existingAppend: StoredNote = {
      id: "ap1",
      parent: "n1",
      author_id: "owner",
      title: "Original Append Title",
      lng: 0,
      lat: 0,
      version: 1,
      sections: [
        {
          order: 0,
          content: "original append content",
          rule_type: "public",
          rule_params: {},
          teaser: false,
          teaser_text: "",
        },
      ],
    };
    await wireRoutes(page, [parentNote, existingAppend]);
    await page.goto("/");

    // Switch to owner persona
    await page.getByRole("button", { name: "You (owner)" }).click();

    // Click the parent note marker → panel shows existing append
    await clickMarkerByIndex(page, 0);
    await expect(page.getByText("original append content")).toBeVisible();

    // Click Edit append button on owner's append
    await page.getByRole("button", { name: /edit append/i }).click();

    // Editor opens in edit-append mode
    await expect(page.getByText(/edit append/i)).toBeVisible();

    // Change the content
    await page.getByLabel("Section content").fill("updated append content");

    // Save
    await page.getByRole("button", { name: /save append/i }).click();

    // Editor closes and updated content is reflected inline
    await expect(page.getByText(/edit append/i)).not.toBeVisible();
    await expect(page.getByText("updated append content")).toBeVisible();
    await expect(page.getByText("original append content")).not.toBeVisible();
  });

  // -------------------------------------------------------------------------
  // 9. Delete own append — append disappears from inline list
  // -------------------------------------------------------------------------
  test("delete own append — append disappears", async ({ page }) => {
    const parentNote: StoredNote = {
      id: "n1",
      author_id: "friend",
      title: "Parent Note",
      lng: -71.0589,
      lat: 42.3601,
      version: 1,
      sections: [
        {
          order: 0,
          content: "parent content",
          rule_type: "public",
          rule_params: {},
          teaser: false,
          teaser_text: "",
        },
      ],
    };
    const existingAppend: StoredNote = {
      id: "ap1",
      parent: "n1",
      author_id: "owner",
      title: "To Be Deleted Append",
      lng: 0,
      lat: 0,
      version: 1,
      sections: [
        {
          order: 0,
          content: "append to delete",
          rule_type: "public",
          rule_params: {},
          teaser: false,
          teaser_text: "",
        },
      ],
    };
    await wireRoutes(page, [parentNote, existingAppend]);
    await page.goto("/");

    // Switch to owner persona
    await page.getByRole("button", { name: "You (owner)" }).click();

    // Click the parent note marker
    await clickMarkerByIndex(page, 0);
    await expect(page.getByText("append to delete")).toBeVisible();

    // Register dialog handler before clicking delete
    page.on("dialog", (d) => d.accept());

    // Click Delete append button
    await page.getByRole("button", { name: /delete append/i }).click();

    // The append content disappears
    await expect(page.getByText("append to delete")).not.toBeVisible();
  });

  // -------------------------------------------------------------------------
  // 10. Visibility independence — persona B cannot see A's private append section
  // -------------------------------------------------------------------------
  test("visibility independence — private append section hidden from other persona", async ({ page }) => {
    const parentNote: StoredNote = {
      id: "n1",
      author_id: "owner",
      title: "Shared Note",
      lng: -71.0589,
      lat: 42.3601,
      version: 1,
      sections: [
        {
          order: 0,
          content: "public note content",
          rule_type: "public",
          rule_params: {},
          teaser: false,
          teaser_text: "",
        },
      ],
    };
    // Append authored by "owner" with TWO sections:
    //   - section 0: public (visible to all)
    //   - section 1: private (only visible to owner)
    const ownerAppend: StoredNote = {
      id: "ap1",
      parent: "n1",
      author_id: "owner",
      title: "Owner's Append",
      lng: 0,
      lat: 0,
      version: 1,
      sections: [
        {
          order: 0,
          content: "public append section",
          rule_type: "public",
          rule_params: {},
          teaser: false,
          teaser_text: "",
        },
        {
          order: 1,
          content: "owner-only private section",
          rule_type: "private",
          rule_params: {},
          teaser: false,
          teaser_text: "",
        },
      ],
    };
    await wireRoutes(page, [parentNote, ownerAppend]);
    await page.goto("/");

    // --- View as "friend" (persona B) ---
    await page.getByRole("button", { name: "A Friend" }).click();

    // Click the parent note marker
    await clickMarkerByIndex(page, 0);
    await expect(page.getByText("Shared Note")).toBeVisible();

    // The parent note is visible
    await expect(page.getByText("public note content")).toBeVisible();

    // The append's PUBLIC section is visible to friend
    await expect(page.getByText("public append section")).toBeVisible();

    // The append's PRIVATE section is NOT visible to friend (key assertion)
    await expect(page.getByText("owner-only private section")).not.toBeVisible();

    // --- Now switch to "owner" (persona A) ---
    await page.getByRole("button", { name: "You (owner)" }).click();

    // The panel should still show (or re-open the note — wait for it)
    // After persona switch, notes reload — click the marker again if panel closed
    await clickMarkerByIndex(page, 0);
    await expect(page.getByText("Shared Note")).toBeVisible();

    // The append's PUBLIC section is visible to owner too
    await expect(page.getByText("public append section")).toBeVisible();

    // The append's PRIVATE section IS visible to its author (owner)
    await expect(page.getByText("owner-only private section")).toBeVisible();
  });
});
