import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { AboutButton } from "./AboutButton";

test("About toggles a popover with the author and a new-tab link to the repo", async () => {
  render(<AboutButton />);

  // Closed by default.
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /about/i }));

  const dialog = screen.getByRole("dialog");
  expect(dialog).toHaveTextContent(/built by david leung/i);
  const link = screen.getByRole("link", { name: /github/i });
  expect(link).toHaveAttribute("href", "https://github.com/dcltdw/annotated-maps-sp");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));

  // Toggles closed again.
  await userEvent.click(screen.getByRole("button", { name: /about/i }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
