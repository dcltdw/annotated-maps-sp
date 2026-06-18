import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

vi.mock("./api/maps", () => ({
  fetchMaps: vi.fn().mockResolvedValue([{ id: "m1", name: "Boston", lng: -71, lat: 42, zoom: 12 }]),
  fetchViewers: vi.fn().mockResolvedValue([
    { id: "u1", display_name: "Owner", reputation: 100 },
    { id: "u2", display_name: "Friend", reputation: 10 },
  ]),
  fetchNotes: vi.fn().mockResolvedValue([
    { id: "n1", author_id: "u1", title: "Castle Island", lng: -71, lat: 42, sections: [
      { id: "s1", order: 0, visibility: "visible", content: "scenic", rule_type: "public", rule_label: "Public", teaser_text: null },
    ], appends: [] },
  ]),
  fetchGroups: vi.fn().mockResolvedValue([{ id: "g1", name: "Running club" }]),
  fetchNoteForEdit: vi.fn().mockResolvedValue({
    id: "n1", title: "Castle Island", lng: -71, lat: 42, version: 1,
    sections: [{ order: 0, content: "scenic", rule_type: "public", rule_params: {}, teaser: false, teaser_text: "" }],
  }),
  createNote: vi.fn().mockResolvedValue({ id: "n2" }),
  updateNote: vi.fn().mockResolvedValue({ id: "n1", version: 2 }),
  deleteNote: vi.fn().mockResolvedValue(null),
}));

// MapView mock that exposes onMapClick so tests can simulate a map canvas click.
let capturedOnMapClick: ((lng: number, lat: number) => void) | undefined;
vi.mock("./components/MapView", () => ({
  MapView: ({ onSelect, onMapClick }: { onSelect: (id: string) => void; onMapClick?: (lng: number, lat: number) => void }) => {
    capturedOnMapClick = onMapClick;
    return (
      <>
        <button onClick={() => onSelect("n1")}>pin n1</button>
        <button onClick={() => onMapClick?.(-71.2, 42.2)}>click map</button>
      </>
    );
  },
}));

// NoteEditor stub: exposes a "Save stub" button that calls onSave with a minimal valid input.
vi.mock("./components/NoteEditor", () => ({
  NoteEditor: ({ onSave, onCancel, existing }: {
    onSave: (n: unknown) => void;
    onCancel: () => void;
    existing?: unknown;
  }) => (
    <div data-testid="note-editor">
      <span>{existing ? "edit-mode" : "create-mode"}</span>
      <button
        onClick={() =>
          onSave(
            existing
              ? { title: "Castle Island", lng: -71, lat: 42, sections: [], version: 1 }
              : { title: "New note", lng: -71.2, lat: 42.2, sections: [] },
          )
        }
      >
        Save stub
      </button>
      <button onClick={onCancel}>Cancel stub</button>
    </div>
  ),
}));

import { MapScreen } from "./MapScreen";
import { createNote, deleteNote, fetchNoteForEdit, fetchNotes } from "./api/maps";

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
