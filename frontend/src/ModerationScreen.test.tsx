import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { ModerationScreen } from "./ModerationScreen";
import * as modApi from "./api/mod";

vi.mock("./api/mod");

const item: modApi.ModItem = {
  id: "n1", kind: "note", title: "spam", snippet: "buy now", author_name: "Alice",
  session_key: "sess-abcdef12", created_ip: "9.9.9.9", created_at: "", updated_at: "",
  version: 1, map_name: "Demo",
};

beforeEach(() => {
  sessionStorage.clear();
  vi.resetAllMocks();
  vi.mocked(modApi.modRecent).mockResolvedValue([item]);
  vi.mocked(modApi.modDelete).mockResolvedValue({ deleted: 1 });
});

test("prompts for a token, then lists recent content", async () => {
  render(<ModerationScreen />);
  await userEvent.type(screen.getByLabelText(/moderation token/i), "secret");
  await userEvent.click(screen.getByRole("button", { name: /unlock/i }));
  expect(await screen.findByText("spam")).toBeInTheDocument();
  expect(modApi.modRecent).toHaveBeenCalledWith("secret");
});

test("deletes selected rows by id", async () => {
  sessionStorage.setItem("modToken", "secret");
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<ModerationScreen />);
  await userEvent.click(await screen.findByLabelText(/select n1/i));
  await userEvent.click(screen.getByRole("button", { name: /delete selected/i }));
  await waitFor(() => expect(modApi.modDelete).toHaveBeenCalledWith("secret", { ids: ["n1"] }));
});
