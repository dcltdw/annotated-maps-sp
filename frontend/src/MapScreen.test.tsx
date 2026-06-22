import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";

vi.mock("./api/maps", () => ({
  fetchMaps: vi.fn().mockResolvedValue([{ id: "m1", name: "Boston", lng: -71, lat: 42, zoom: 12 }]),
  fetchViewers: vi.fn().mockResolvedValue([
    { id: "u1", display_name: "Owner", reputation: 100 },
    { id: "u2", display_name: "Friend", reputation: 10 },
  ]),
  // editable mirrors the server: true only when the viewer (preview_as) authored the note/append (u1).
  fetchNotes: vi.fn().mockImplementation((_mapId: string, previewAs: string | null) => {
    const own = previewAs === "u1";
    return Promise.resolve([
      { id: "n1", author_id: "u1", title: "Castle Island", lng: -71, lat: 42, editable: own, shape: null, sections: [
        { id: "s1", order: 0, visibility: "visible", content: "scenic", rule_type: "public", rule_label: "Public", teaser_text: null },
      ], appends: [
        { id: "ap1", author_id: "u1", author_name: "Owner", title: "Append tip", editable: own, sections: [
          { id: "as1", order: 0, visibility: "visible", content: "great view", rule_type: "public", rule_label: "Public", teaser_text: null },
        ]},
      ]},
    ]);
  }),
  fetchGroups: vi.fn().mockResolvedValue([{ id: "g1", name: "Running club" }]),
  fetchNoteForEdit: vi.fn().mockResolvedValue({
    id: "n1", title: "Castle Island", lng: -71, lat: 42, version: 1,
    sections: [{ order: 0, content: "scenic", rule_type: "public", rule_params: {}, teaser: false, teaser_text: "" }],
  }),
  createNote: vi.fn().mockResolvedValue({ id: "n2" }),
  updateNote: vi.fn().mockResolvedValue({ id: "n1", version: 2 }),
  deleteNote: vi.fn().mockResolvedValue(null),
  createAppend: vi.fn().mockResolvedValue({ id: "ap1" }),
  updateAppend: vi.fn().mockResolvedValue({ id: "ap1", version: 2 }),
}));

// MapView mock that exposes onMapClick + the draw-area wiring (drawMode/onShapeDrawn) so
// tests can simulate a map canvas click and a finished polygon without real terra-draw.
let capturedOnMapClick: ((lng: number, lat: number) => void) | undefined;
vi.mock("./components/MapView", () => ({
  MapView: ({ onSelect, onMapClick, drawMode, onShapeDrawn }: {
    onSelect: (id: string) => void;
    onMapClick?: (lng: number, lat: number) => void;
    drawMode?: string | null;
    onShapeDrawn?: (shape: unknown) => void;
  }) => {
    capturedOnMapClick = onMapClick;
    return (
      <>
        <span data-testid="draw-mode">{drawMode ?? "none"}</span>
        <button onClick={() => onSelect("n1")}>pin n1</button>
        <button onClick={() => onMapClick?.(-71.2, 42.2)}>click map</button>
        <button onClick={() => onShapeDrawn?.({ kind: "polygon", coordinates: [[-71, 42], [-71, 43], [-72, 43]] })}>
          finish polygon
        </button>
        <button onClick={() => onShapeDrawn?.({ kind: "line", coordinates: [[-71, 42], [-71, 43]] })}>
          finish line
        </button>
      </>
    );
  },
}));

// NoteEditor stub: exposes a "Save stub" button that calls onSave with a minimal valid input.
vi.mock("./components/NoteEditor", () => ({
  NoteEditor: ({ onSave, onCancel, existing, variant, shape }: {
    onSave: (n: unknown) => void;
    onCancel: () => void;
    existing?: unknown;
    variant?: string;
    shape?: unknown;
  }) => (
    <div data-testid="note-editor">
      <span>{existing ? "edit-mode" : "create-mode"}</span>
      <span data-testid="editor-variant">{variant ?? "note"}</span>
      <span data-testid="editor-has-shape">{shape ? "shape" : "point"}</span>
      <button
        onClick={() => {
          // Mirror the real editor: a shape anchor replaces lng/lat.
          const anchor = shape ? { shape } : { lng: -71.2, lat: 42.2 };
          onSave(
            existing
              ? { title: "Castle Island", lng: -71, lat: 42, sections: [], version: 1, ...(shape ? { shape } : {}) }
              : { title: "New note", sections: [], ...anchor },
          );
        }}
      >
        Save stub
      </button>
      <button onClick={onCancel}>Cancel stub</button>
    </div>
  ),
}));

vi.mock("./api/auth", () => ({
  me: vi.fn(() => Promise.resolve(null)),
  // AuthBar imports login/signup/logout; provide no-op stubs so the real AuthBar renders.
  login: vi.fn(),
  signup: vi.fn(),
  logout: vi.fn(() => Promise.resolve()),
}));

import { MapScreen } from "./MapScreen";
import { me as meMock } from "./api/auth";
import { createAppend, createNote, deleteNote, fetchNoteForEdit, fetchNotes, updateAppend } from "./api/maps";

// Reset me() to its default (logged-out) between tests so a queued mockResolvedValueOnce
// from one test cannot leak into the next.
beforeEach(() => {
  vi.mocked(meMock).mockReset();
  vi.mocked(meMock).mockResolvedValue(null);
});

test("loads Boston as Guest, opens a note, and re-fetches when the viewer changes", async () => {
  render(<MapScreen />);
  await screen.findByRole("button", { name: "pin n1" });
  expect(fetchNotes).toHaveBeenNthCalledWith(1, "m1", null); // initial Guest load

  await userEvent.click(screen.getByRole("button", { name: "pin n1" }));
  expect(await screen.findByText(/Castle Island/)).toBeInTheDocument();
  expect(screen.getByText("scenic")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Owner" }));
  await waitFor(() => expect(fetchNotes).toHaveBeenLastCalledWith("m1", "u1"));
});

test("collapses the note panel with ✕ and reopens it with the ◀ note tab", async () => {
  render(<MapScreen />);
  await screen.findByRole("button", { name: "pin n1" });
  await userEvent.click(screen.getByRole("button", { name: "pin n1" }));
  expect(await screen.findByText(/Castle Island/)).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /collapse panel/i }));
  expect(screen.queryByText(/Castle Island/)).not.toBeInTheDocument(); // panel gone

  await userEvent.click(screen.getByRole("button", { name: /note/i })); // ◀ note tab
  expect(await screen.findByText(/Castle Island/)).toBeInTheDocument(); // reopened
});

test("as a persona, clicking the map opens the NoteEditor in create mode", async () => {
  render(<MapScreen />);
  await screen.findByRole("button", { name: "pin n1" });
  // Switch to persona
  await userEvent.click(screen.getByRole("button", { name: "Owner" }));
  await waitFor(() => expect(fetchNotes).toHaveBeenCalledWith("m1", "u1"));

  // Simulate map canvas click
  await userEvent.click(screen.getByRole("button", { name: "click map" }));
  expect(await screen.findByTestId("note-editor")).toBeInTheDocument();
  expect(screen.getByText("create-mode")).toBeInTheDocument();
});

test("Draw route arms line mode and finishing a line opens the editor in create mode", async () => {
  render(<MapScreen />);
  await screen.findByRole("button", { name: "pin n1" });
  await userEvent.click(screen.getByRole("button", { name: "Owner" }));
  await waitFor(() => expect(fetchNotes).toHaveBeenCalledWith("m1", "u1"));

  // Arm line draw mode via the "Draw route" button
  expect(screen.getByTestId("draw-mode").textContent).toBe("none");
  await userEvent.click(screen.getByRole("button", { name: /draw route/i }));
  expect(screen.getByTestId("draw-mode").textContent).toBe("line");

  // Emit a finished line shape → editor opens in create mode with a shape anchor
  await userEvent.click(screen.getByRole("button", { name: "finish line" }));
  expect(await screen.findByTestId("note-editor")).toBeInTheDocument();
  expect(screen.getByText("create-mode")).toBeInTheDocument();
  expect(screen.getByTestId("editor-has-shape").textContent).toBe("shape");
});

test("Draw circle arms circle mode and finishing a polygon opens the editor in create mode with a shape anchor", async () => {
  render(<MapScreen />);
  await screen.findByRole("button", { name: "pin n1" });
  await userEvent.click(screen.getByRole("button", { name: "Owner" }));
  await waitFor(() => expect(fetchNotes).toHaveBeenCalledWith("m1", "u1"));

  // Arm circle draw mode via the "Draw circle" button
  expect(screen.getByTestId("draw-mode").textContent).toBe("none");
  await userEvent.click(screen.getByRole("button", { name: /draw circle/i }));
  expect(screen.getByTestId("draw-mode").textContent).toBe("circle");

  // Emit a finished polygon shape (terra-draw circle adapter emits a polygon) → editor opens in create mode with a shape anchor
  await userEvent.click(screen.getByRole("button", { name: "finish polygon" }));
  expect(await screen.findByTestId("note-editor")).toBeInTheDocument();
  expect(screen.getByText("create-mode")).toBeInTheDocument();
  expect(screen.getByTestId("editor-has-shape").textContent).toBe("shape");
});

test("create: save calls createNote then re-fetches notes", async () => {
  render(<MapScreen />);
  await screen.findByRole("button", { name: "pin n1" });
  await userEvent.click(screen.getByRole("button", { name: "Owner" }));
  await waitFor(() => expect(fetchNotes).toHaveBeenCalledWith("m1", "u1"));
  const fetchNotesBefore = (fetchNotes as ReturnType<typeof vi.fn>).mock.calls.length;

  await userEvent.click(screen.getByRole("button", { name: "click map" }));
  await screen.findByTestId("note-editor");
  await userEvent.click(screen.getByRole("button", { name: "Save stub" }));
  expect(createNote).toHaveBeenCalled();
  await waitFor(() =>
    expect((fetchNotes as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(fetchNotesBefore),
  );
  // Editor gone after save
  expect(screen.queryByTestId("note-editor")).not.toBeInTheDocument();
});

test("clicking ✎ on own note opens editor in edit mode", async () => {
  render(<MapScreen />);
  await screen.findByRole("button", { name: "pin n1" });
  await userEvent.click(screen.getByRole("button", { name: "Owner" }));
  await waitFor(() => expect(fetchNotes).toHaveBeenCalledWith("m1", "u1"));

  // Select the note (author_id "u1" === previewAs "u1" → canEdit)
  await userEvent.click(screen.getByRole("button", { name: "pin n1" }));
  await screen.findByText(/Castle Island/);

  await userEvent.click(screen.getByRole("button", { name: /edit note/i }));
  expect(fetchNoteForEdit).toHaveBeenCalledWith("n1", "u1");
  expect(await screen.findByText("edit-mode")).toBeInTheDocument();
});

test("delete own note calls deleteNote then re-fetches", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<MapScreen />);
  await screen.findByRole("button", { name: "pin n1" });
  await userEvent.click(screen.getByRole("button", { name: "Owner" }));
  await waitFor(() => expect(fetchNotes).toHaveBeenCalledWith("m1", "u1"));
  const fetchNotesBefore = (fetchNotes as ReturnType<typeof vi.fn>).mock.calls.length;

  await userEvent.click(screen.getByRole("button", { name: "pin n1" }));
  await screen.findByText(/Castle Island/);
  await userEvent.click(screen.getByRole("button", { name: /delete note/i }));
  expect(deleteNote).toHaveBeenCalledWith("n1", "u1");
  await waitFor(() =>
    expect((fetchNotes as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(fetchNotesBefore),
  );
  vi.restoreAllMocks();
});

test("as Guest, clicking the map does NOT open the editor", async () => {
  render(<MapScreen />);
  await screen.findByRole("button", { name: "pin n1" });
  // Guest: no previewAs, so onMapClick should be undefined / not passed to MapView
  expect(capturedOnMapClick).toBeUndefined();
  // Clicking the "click map" button should not open the editor
  await userEvent.click(screen.getByRole("button", { name: "click map" }));
  expect(screen.queryByTestId("note-editor")).not.toBeInTheDocument();
});

test("as Guest, selected note shows no ✎/Delete buttons (canEdit=false)", async () => {
  render(<MapScreen />);
  await screen.findByRole("button", { name: "pin n1" });
  await userEvent.click(screen.getByRole("button", { name: "pin n1" }));
  await screen.findByText(/Castle Island/);
  expect(screen.queryByRole("button", { name: /edit note/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /delete note/i })).not.toBeInTheDocument();
});

test("a non-author persona viewing someone else's note shows no ✎/Delete", async () => {
  render(<MapScreen />);
  await screen.findByRole("button", { name: "pin n1" });
  // View as Friend (u2); the seeded note is authored by u1 → not own → no write affordances.
  await userEvent.click(screen.getByRole("button", { name: "Friend" }));
  await waitFor(() => expect(fetchNotes).toHaveBeenCalledWith("m1", "u2"));
  await userEvent.click(screen.getByRole("button", { name: "pin n1" }));
  await screen.findByText(/Castle Island/);
  expect(screen.queryByRole("button", { name: /edit note/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /delete note/i })).not.toBeInTheDocument();
});

test("＋Append opens the editor in append variant and save calls createAppend then re-fetches", async () => {
  render(<MapScreen />);
  await screen.findByRole("button", { name: "pin n1" });
  // Switch to persona so canWrite = true
  await userEvent.click(screen.getByRole("button", { name: "Owner" }));
  await waitFor(() => expect(fetchNotes).toHaveBeenCalledWith("m1", "u1"));

  // Select note to open panel
  await userEvent.click(screen.getByRole("button", { name: "pin n1" }));
  await screen.findByText(/Castle Island/);

  const fetchNotesBefore = (fetchNotes as ReturnType<typeof vi.fn>).mock.calls.length;

  // Click the ＋ Append button
  await userEvent.click(screen.getByRole("button", { name: /append to this note/i }));
  await screen.findByTestId("note-editor");
  expect(screen.getByTestId("editor-variant").textContent).toBe("append");
  expect(screen.getByText("create-mode")).toBeInTheDocument();

  // Save the append
  await userEvent.click(screen.getByRole("button", { name: "Save stub" }));
  expect(createAppend).toHaveBeenCalledWith("n1", expect.objectContaining({ title: expect.any(String), sections: expect.any(Array) }), "u1");
  // appends carry no coordinates — lng/lat must be dropped from the editor payload
  const appendPayload = (createAppend as ReturnType<typeof vi.fn>).mock.calls[0][1];
  expect(appendPayload).not.toHaveProperty("lng");
  expect(appendPayload).not.toHaveProperty("lat");
  await waitFor(() =>
    expect((fetchNotes as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(fetchNotesBefore),
  );
  // Editor gone after save
  expect(screen.queryByTestId("note-editor")).not.toBeInTheDocument();
});

test("clicking ✎ on own append opens editor in edit-append variant and save calls updateAppend", async () => {
  render(<MapScreen />);
  await screen.findByRole("button", { name: "pin n1" });
  // Switch to persona u1 (the append author)
  await userEvent.click(screen.getByRole("button", { name: "Owner" }));
  await waitFor(() => expect(fetchNotes).toHaveBeenCalledWith("m1", "u1"));

  // Select the note so NotePanel renders with the append
  await userEvent.click(screen.getByRole("button", { name: "pin n1" }));
  await screen.findByText(/Castle Island/);
  // fetchNoteForEdit for the append returns the APPEND's raw data (id ap1, version 3, no point)
  (fetchNoteForEdit as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
    id: "ap1", title: "T", lng: null, lat: null, version: 3, sections: [],
  });
  // The append is visible; click its edit button
  await userEvent.click(screen.getByRole("button", { name: /edit append/i }));
  expect(fetchNoteForEdit).toHaveBeenCalledWith("ap1", "u1");

  await screen.findByTestId("note-editor");
  expect(screen.getByTestId("editor-variant").textContent).toBe("append");
  expect(screen.getByText("edit-mode")).toBeInTheDocument();

  const fetchNotesBefore = (fetchNotes as ReturnType<typeof vi.fn>).mock.calls.length;
  await userEvent.click(screen.getByRole("button", { name: "Save stub" }));
  // targets the APPEND's own id (ap1, from fetchNoteForEdit) with its version, no lng/lat
  expect(updateAppend).toHaveBeenCalledWith("ap1", expect.objectContaining({ version: 3 }), "u1");
  const updPayload = (updateAppend as ReturnType<typeof vi.fn>).mock.calls[0][1];
  expect(updPayload).not.toHaveProperty("lng");
  await waitFor(() =>
    expect((fetchNotes as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(fetchNotesBefore),
  );
  expect(screen.queryByTestId("note-editor")).not.toBeInTheDocument();
});

test("⋯ on own append calls deleteNote then re-fetches", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<MapScreen />);
  await screen.findByRole("button", { name: "pin n1" });
  await userEvent.click(screen.getByRole("button", { name: "Owner" }));
  await waitFor(() => expect(fetchNotes).toHaveBeenCalledWith("m1", "u1"));
  await userEvent.click(screen.getByRole("button", { name: "pin n1" }));
  await screen.findByText(/Castle Island/);
  const before = (fetchNotes as ReturnType<typeof vi.fn>).mock.calls.length;
  await userEvent.click(screen.getByRole("button", { name: /delete append/i }));
  expect(deleteNote).toHaveBeenCalledWith("ap1", "u1");
  await waitFor(() =>
    expect((fetchNotes as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(before),
  );
  vi.restoreAllMocks();
});

test("restores an authenticated user via me() and hides the persona switcher", async () => {
  const { me } = await import("./api/auth");
  (me as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
    id: "u1", email: "a@x.com", display_name: "Ada", reputation: 0,
  });
  render(<MapScreen />);
  // The logged-in chip shows the user; the "Viewing as" persona switcher is gone.
  expect(await screen.findByText(/Ada/)).toBeInTheDocument();
  expect(screen.queryByText("Viewing as")).not.toBeInTheDocument();
});

test("a logged-out visitor sees the persona switcher and a Log in button", async () => {
  render(<MapScreen />);
  expect(await screen.findByText("Viewing as")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /log in/i })).toBeInTheDocument();
});
