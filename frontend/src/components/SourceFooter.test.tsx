import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { SourceFooter } from "./SourceFooter";

test("names the licence and offers the source in a new tab (AGPL section 13)", () => {
  render(<SourceFooter />);

  // The licence has to be identifiable, not just "source available".
  expect(screen.getByText(/AGPL-3\.0-or-later/)).toBeInTheDocument();

  const link = screen.getByRole("link", { name: /source/i });
  expect(link).toHaveAttribute("href", "https://github.com/dcltdw/annotated-maps-sp");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));

  // Always visible: the offer must not be behind a disclosure control.
  expect(screen.getByRole("contentinfo")).toBeInTheDocument();
});
