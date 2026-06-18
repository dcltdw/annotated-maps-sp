import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { NoteEditor } from "./NoteEditor";
import type { NoteEdit } from "../api/types";

const groups = [{ id: "g1", name: "Running club" }];

test("builds a NoteInput and calls onSave", async () => {
  const onSave = vi.fn();
  render(<NoteEditor lng={-71} lat={42} groups={groups} authorLabel="You (owner)" onSave={onSave} onCancel={() => {}} />);
  await userEvent.type(screen.getByLabelText(/title/i), "Esplanade bench");
  await userEvent.type(screen.getByLabelText(/section content/i), "calm spot");
  await userEvent.click(screen.getByRole("button", { name: /save/i }));
  expect(onSave).toHaveBeenCalledWith(
    expect.objectContaining({ title: "Esplanade bench", lng: -71, lat: 42, sections: expect.any(Array) }),
  );
});

test("blocks save with an empty title and shows an error", async () => {
  const onSave = vi.fn();
  render(<NoteEditor lng={-71} lat={42} groups={groups} authorLabel="You" onSave={onSave} onCancel={() => {}} />);
  await userEvent.type(screen.getByLabelText(/section content/i), "x");
  await userEvent.click(screen.getByRole("button", { name: /save/i }));
  expect(onSave).not.toHaveBeenCalled();
  expect(screen.getByText(/title is required/i)).toBeInTheDocument();
});

test("add section adds a second card; remove takes it away", async () => {
  render(<NoteEditor lng={-71} lat={42} groups={groups} authorLabel="You" onSave={() => {}} onCancel={() => {}} />);
  expect(screen.getAllByLabelText(/section content/i)).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: /add section/i }));
  expect(screen.getAllByLabelText(/section content/i)).toHaveLength(2);
  await userEvent.click(screen.getAllByRole("button", { name: /remove section/i })[1]);
  expect(screen.getAllByLabelText(/section content/i)).toHaveLength(1);
});

test("append variant: title optional, append labels, saves with empty title", async () => {
  const onSave = vi.fn();
  render(<NoteEditor lng={-71} lat={42} groups={groups} authorLabel="A Friend" variant="append" onSave={onSave} onCancel={() => {}} />);
  expect(screen.getByText(/new append/i)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText(/section content/i), "sunset tip");
  await userEvent.click(screen.getByRole("button", { name: /save/i }));
  // no "title is required" error; onSave called even with a blank title
  expect(screen.queryByText(/title is required/i)).not.toBeInTheDocument();
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ title: "", sections: expect.any(Array) }));
});

test("edit mode pre-fills from the existing note and emits version on save", async () => {
  const onSave = vi.fn();
  const existing: NoteEdit = {
    id: "n1",
    title: "Old title",
    lng: -71,
    lat: 42,
    version: 4,
    sections: [
      { order: 0, content: "existing body", rule_type: "public", rule_params: {}, teaser: false, teaser_text: "" },
    ],
  };
  render(
    <NoteEditor lng={-71} lat={42} groups={groups} authorLabel="You" existing={existing} onSave={onSave} onCancel={() => {}} />,
  );
  // pre-filled
  expect((screen.getByLabelText(/title/i) as HTMLInputElement).value).toBe("Old title");
  expect((screen.getByLabelText(/section content/i) as HTMLTextAreaElement).value).toBe("existing body");
  // save emits the version (NoteUpdateInput)
  await userEvent.click(screen.getByRole("button", { name: /save/i }));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ title: "Old title", version: 4 }));
});
