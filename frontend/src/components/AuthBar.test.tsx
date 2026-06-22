import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { AuthBar } from "./AuthBar";
import * as auth from "../api/auth";

afterEach(() => vi.restoreAllMocks());

const USER = { id: "u1", email: "a@x.com", display_name: "Ada", reputation: 0 };

test("logged out: shows a Log in button and the persona switcher is the caller's concern", () => {
  render(<AuthBar user={null} onAuthed={() => {}} onLoggedOut={() => {}} />);
  expect(screen.getByRole("button", { name: /log in/i })).toBeInTheDocument();
});

test("opening the popover and submitting logs in and reports the user", async () => {
  const spy = vi.spyOn(auth, "login").mockResolvedValue(USER);
  const onAuthed = vi.fn();
  render(<AuthBar user={null} onAuthed={onAuthed} onLoggedOut={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: /log in/i }));
  await userEvent.type(screen.getByLabelText(/email/i), "a@x.com");
  await userEvent.type(screen.getByLabelText(/password/i), "longenough");
  await userEvent.click(screen.getByRole("button", { name: /^log in$/i }));
  await waitFor(() => expect(onAuthed).toHaveBeenCalledWith(USER));
  expect(spy).toHaveBeenCalledWith("a@x.com", "longenough");
});

test("the demo-login hint is shown in the popover", async () => {
  render(<AuthBar user={null} onAuthed={() => {}} onLoggedOut={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: /log in/i }));
  expect(screen.getByText(/friend@demo\.example/)).toBeInTheDocument();
});

test("toggling to sign up calls signup with the display name", async () => {
  const spy = vi.spyOn(auth, "signup").mockResolvedValue(USER);
  const onAuthed = vi.fn();
  render(<AuthBar user={null} onAuthed={onAuthed} onLoggedOut={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: /log in/i }));
  await userEvent.click(screen.getByRole("button", { name: /need an account/i }));
  await userEvent.type(screen.getByLabelText(/display name/i), "Ada");
  await userEvent.type(screen.getByLabelText(/email/i), "a@x.com");
  await userEvent.type(screen.getByLabelText(/password/i), "longenough");
  await userEvent.click(screen.getByRole("button", { name: /^sign up$/i }));
  await waitFor(() => expect(spy).toHaveBeenCalledWith("a@x.com", "longenough", "Ada"));
  await waitFor(() => expect(onAuthed).toHaveBeenCalledWith(USER));
});

test("a failed login shows an error and does not report a user", async () => {
  vi.spyOn(auth, "login").mockRejectedValue(new Error("nope"));
  const onAuthed = vi.fn();
  render(<AuthBar user={null} onAuthed={onAuthed} onLoggedOut={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: /log in/i }));
  await userEvent.type(screen.getByLabelText(/email/i), "a@x.com");
  await userEvent.type(screen.getByLabelText(/password/i), "wrong");
  await userEvent.click(screen.getByRole("button", { name: /^log in$/i }));
  await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  expect(onAuthed).not.toHaveBeenCalled();
});

test("logged in: shows the name and Log out triggers logout + onLoggedOut", async () => {
  const spy = vi.spyOn(auth, "logout").mockResolvedValue();
  const onLoggedOut = vi.fn();
  render(<AuthBar user={USER} onAuthed={() => {}} onLoggedOut={onLoggedOut} />);
  expect(screen.getByText(/Ada/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /log out/i }));
  await waitFor(() => expect(onLoggedOut).toHaveBeenCalled());
  expect(spy).toHaveBeenCalled();
});
