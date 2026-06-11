import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

vi.mock("./api/maps", () => ({
  fetchMaps: vi.fn().mockResolvedValue([{ id: "m1", name: "Boston", lng: -71, lat: 42, zoom: 12 }]),
  fetchViewers: vi.fn().mockResolvedValue([{ id: "u1", display_name: "Owner", reputation: 100 }]),
  fetchNotes: vi.fn().mockResolvedValue([
    { id: "n1", title: "Castle Island", lng: -71, lat: 42, sections: [
      { id: "s1", order: 0, visibility: "visible", content: "scenic", rule_type: "public", rule_label: "Public" },
    ] },
  ]),
}));
vi.mock("./components/MapView", () => ({
  MapView: ({ onSelect }: { onSelect: (id: string) => void }) => (
    <button onClick={() => onSelect("n1")}>pin n1</button>
  ),
}));

import { MapScreen } from "./MapScreen";
import { fetchNotes } from "./api/maps";

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
