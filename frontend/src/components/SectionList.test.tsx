import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { SectionList } from "./SectionList";
import type { SectionOut } from "../api/types";

const sections: SectionOut[] = [
  { id: "a", order: 0, visibility: "visible", content: "shown", rule_type: "public", rule_label: "Public", teaser_text: null },
  { id: "b", order: 1, visibility: "teaser", content: null, rule_type: "audience", rule_label: "Club", teaser_text: "hook" },
];

test("renders visible content and the teaser hook", () => {
  render(<SectionList sections={sections} />);
  expect(screen.getByText("shown")).toBeInTheDocument();
  expect(screen.getByText("hook")).toBeInTheDocument(); // teaser_text
});
