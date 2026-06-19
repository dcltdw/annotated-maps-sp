import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { NotePanel } from "./NotePanel";
import type { NoteOut } from "../api/types";

const note: NoteOut = {
  id: "n1", title: "Castle Island", lng: -71, lat: 42, author_id: "u1", editable: false,
  sections: [
    { id: "s1", order: 0, visibility: "visible", content: "scenic loop", rule_type: "public", rule_label: "Public", teaser_text: null },
    { id: "s2", order: 1, visibility: "teaser", content: null, rule_type: "audience", rule_label: "Running club", teaser_text: "ask me nicely" },
  ],
  appends: [],
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

test("canEdit=true renders edit and delete buttons that fire their callbacks", async () => {
  const onEdit = vi.fn();
  const onDelete = vi.fn();
  // Stub window.confirm to return true
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(
    <NotePanel
      note={note}
      viewerLabel="Owner"
      onCollapse={() => {}}
      canEdit
      onEdit={onEdit}
      onDelete={onDelete}
    />,
  );
  expect(screen.getByRole("button", { name: /edit note/i })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /delete note/i })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /edit note/i }));
  expect(onEdit).toHaveBeenCalledOnce();
  await userEvent.click(screen.getByRole("button", { name: /delete note/i }));
  expect(window.confirm).toHaveBeenCalled();
  expect(onDelete).toHaveBeenCalledOnce();
  vi.restoreAllMocks();
});

test("canEdit=false (default) renders neither edit nor delete button", () => {
  render(<NotePanel note={note} viewerLabel="Guest" onCollapse={() => {}} canEdit={false} />);
  expect(screen.queryByRole("button", { name: /edit note/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /delete note/i })).not.toBeInTheDocument();
});

test("renders appends inline: own is editable, others read-only, ＋Append present", async () => {
  const onAppend = vi.fn(), onEditAppend = vi.fn(), onDeleteAppend = vi.fn();
  const noteWithAppends: NoteOut = {
    ...note,
    appends: [
      { id: "ap1", author_id: "me", author_name: "A Friend", title: "Sunset tip", editable: true,
        sections: [{ id: "s", order: 0, visibility: "visible", content: "go at dusk", rule_type: "public", rule_label: "Public", teaser_text: null }] },
      { id: "ap2", author_id: "other", author_name: "Run-club", title: "", editable: false,
        sections: [{ id: "s2", order: 0, visibility: "visible", content: "sat 8am", rule_type: "public", rule_label: "Public", teaser_text: null }] },
    ],
  };
  render(<NotePanel note={noteWithAppends} viewerLabel="Me" onCollapse={() => {}} previewAs="me"
    onAppend={onAppend} onEditAppend={onEditAppend} onDeleteAppend={onDeleteAppend} />);
  expect(screen.getByText("A Friend")).toBeInTheDocument();
  expect(screen.getByText("Sunset tip")).toBeInTheDocument();
  expect(screen.getByText("go at dusk")).toBeInTheDocument();
  // only the viewer's OWN append (author "me") shows edit/delete — NOT "other"'s
  expect(screen.getAllByRole("button", { name: /edit append/i })).toHaveLength(1);
  expect(screen.getAllByRole("button", { name: /delete append/i })).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: /edit append/i }));
  expect(onEditAppend).toHaveBeenCalledWith("ap1");
  expect(screen.getByRole("button", { name: /append to this note/i })).toBeInTheDocument();
});

test("append edit controls (✎) render only for appends with editable: true", () => {
  const noteWithAppends: NoteOut = {
    ...note,
    appends: [
      { id: "ap1", author_id: "x", author_name: "Editable one", title: "", editable: true,
        sections: [{ id: "s", order: 0, visibility: "visible", content: "yes", rule_type: "public", rule_label: "Public", teaser_text: null }] },
      { id: "ap2", author_id: "y", author_name: "Locked one", title: "", editable: false,
        sections: [{ id: "s2", order: 0, visibility: "visible", content: "no", rule_type: "public", rule_label: "Public", teaser_text: null }] },
    ],
  };
  render(<NotePanel note={noteWithAppends} viewerLabel="Me" onCollapse={() => {}} previewAs="me" />);
  expect(screen.getAllByRole("button", { name: /edit append/i })).toHaveLength(1);
});

test("a guest (previewAs null) sees no ＋Append and no append edit/delete", () => {
  const noteWithAppends: NoteOut = { ...note, appends: [
    { id: "ap2", author_id: "other", author_name: "Run-club", title: "", editable: false,
      sections: [{ id: "s2", order: 0, visibility: "visible", content: "sat 8am", rule_type: "public", rule_label: "Public", teaser_text: null }] }] };
  render(<NotePanel note={noteWithAppends} viewerLabel="Guest" onCollapse={() => {}} previewAs={null} />);
  expect(screen.queryByRole("button", { name: /append to this note/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /edit append/i })).not.toBeInTheDocument();
});
