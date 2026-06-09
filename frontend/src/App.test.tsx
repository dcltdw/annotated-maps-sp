import { render, screen, waitFor } from "@testing-library/react";
import { test, expect, vi } from "vitest";
import App from "./App";

vi.mock("./api/health", () => ({ fetchHealth: () => Promise.resolve({ status: "ok", version: "1.0.0" }) }));

test("shows connected status once health resolves", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByText("Connected")).toBeInTheDocument());
});
