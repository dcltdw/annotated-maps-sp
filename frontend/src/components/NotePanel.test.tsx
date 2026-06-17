import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { NotePanel } from "./NotePanel";
import type { NoteOut } from "../api/types";

const note: NoteOut = {
  id: "n1", title: "Castle Island", lng: -71, lat: 42, author_id: "u1",
  sections: [
    { id: "s1", order: 0, visibility: "visible", content: "scenic loop", rule_type: "public", rule_label: "Public", teaser_text: null },
    { id: "s2", order: 1, visibility: "teaser", content: null, rule_type: "audience", rule_label: "Running club", teaser_text: "ask me nicely" },
  ],
};

test("renders visible content and a locked teaser, and collapses", async () => {
  const onCollapse = vi.fn();
  render(<NotePanel note={note} viewerLabel="Owner" onCollapse={onCollapse} />);
  expect(screen.getByText("scenic loop")).toBeInTheDocument();
  expect(screen.getByText(/Running club/)).toBeInTheDocument();
  expect(screen.getByText("ask me nicely")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /collapse/i }));
  expect(onCollapse).toHaveBeenCalledOnce();
});

test("shows an empty-state when no sections are visible", () => {
  render(<NotePanel note={{ ...note, sections: [] }} viewerLabel="Guest" onCollapse={() => {}} />);
  expect(screen.getByText(/Nothing here for Guest/i)).toBeInTheDocument();
});

test("never renders a teaser section's content, even if present", () => {
  // Defense-in-depth: the backend nulls teaser content, but the panel must not leak it
  // even if a non-null value somehow reaches the component.
  const leaky: NoteOut = {
    ...note,
    sections: [
      {
        id: "s3",
        order: 0,
        visibility: "teaser",
        content: "members-only secret",
        rule_type: "audience",
        rule_label: "Running club",
        teaser_text: null,
      },
    ],
  };
  render(<NotePanel note={leaky} viewerLabel="Guest" onCollapse={() => {}} />);
  expect(screen.queryByText("members-only secret")).not.toBeInTheDocument();
  expect(screen.getByText(/Locked/i)).toBeInTheDocument();
});

test("shows the section's custom teaser text when present", () => {
  render(<NotePanel note={note} viewerLabel="Guest" onCollapse={() => {}} />);
  expect(screen.getByText("ask me nicely")).toBeInTheDocument();
});
