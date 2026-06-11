import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { PreviewSwitcher } from "./PreviewSwitcher";

const viewers = [{ id: "u1", display_name: "Owner", reputation: 100 }];

test("guest is the default and selecting a viewer fires onChange", async () => {
  const onChange = vi.fn();
  render(<PreviewSwitcher viewers={viewers} current={null} onChange={onChange} />);
  expect(screen.getByRole("button", { name: "Guest" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(screen.getByRole("button", { name: "Owner" }));
  expect(onChange).toHaveBeenCalledWith("u1");
  await userEvent.click(screen.getByRole("button", { name: "Guest" }));
  expect(onChange).toHaveBeenCalledWith(null);
});

test("marks the current viewer pressed", () => {
  render(<PreviewSwitcher viewers={viewers} current="u1" onChange={() => {}} />);
  expect(screen.getByRole("button", { name: "Owner" })).toHaveAttribute("aria-pressed", "true");
});
