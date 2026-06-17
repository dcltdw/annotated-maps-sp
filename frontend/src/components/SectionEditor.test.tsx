import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, test, vi } from "vitest";
import { SectionEditor } from "./SectionEditor";
import type { SectionInput } from "../api/types";

const base: SectionInput = {
  order: 0,
  content: "hi",
  rule_type: "public",
  rule_params: {},
  teaser: false,
  teaser_text: "",
};
const groups = [{ id: "g1", name: "Running club" }];

// Controlled-component harness: owns the section state (as the real NoteEditor parent
// does) and forwards each change to a spy so tests can assert the emitted SectionInput.
function Harness({ initial, onChange }: { initial: SectionInput; onChange?: (s: SectionInput) => void }) {
  const [section, setSection] = useState(initial);
  return (
    <SectionEditor
      section={section}
      groups={groups}
      onChange={(next) => {
        setSection(next);
        onChange?.(next);
      }}
      onRemove={() => {}}
    />
  );
}

test("switching to Audience emits audience rule and reveals the group picker", async () => {
  const onChange = vi.fn();
  render(<Harness initial={base} onChange={onChange} />);
  await userEvent.click(screen.getByRole("button", { name: "Audience" }));
  expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ rule_type: "audience" }));
  expect(screen.getByRole("button", { name: /Running club/ })).toBeInTheDocument();
});

test("Reputation reveals a threshold input that drives rule_params", async () => {
  const onChange = vi.fn();
  render(
    <Harness
      initial={{ ...base, rule_type: "attribute_gate", rule_params: { attribute: "reputation", threshold: 50 } }}
      onChange={onChange}
    />,
  );
  const field = screen.getByLabelText(/reputation/i);
  await userEvent.clear(field);
  await userEvent.type(field, "70");
  expect(onChange).toHaveBeenLastCalledWith(
    expect.objectContaining({ rule_params: expect.objectContaining({ threshold: 70 }) }),
  );
});

test("Public hides the teaser control; non-Public shows it", () => {
  const { rerender } = render(
    <SectionEditor section={base} groups={groups} onChange={() => {}} onRemove={() => {}} />,
  );
  expect(screen.queryByLabelText(/teaser/i)).not.toBeInTheDocument();
  rerender(
    <SectionEditor section={{ ...base, rule_type: "private" }} groups={groups} onChange={() => {}} onRemove={() => {}} />,
  );
  expect(screen.getByLabelText(/teaser/i)).toBeInTheDocument();
});
