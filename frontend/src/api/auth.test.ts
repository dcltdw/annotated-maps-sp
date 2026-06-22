import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  clearToken as _clearToken, // exported but tested via side-effects (getToken checks)
  getToken,
  login,
  logout,
  me,
  signup,
} from "./auth";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

function mockOnce(body: unknown, status = 200) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(() => Promise.resolve(new Response(JSON.stringify(body), { status })));
}

test("login stores the token and returns the user", async () => {
  const user = { id: "u1", email: "a@x.com", display_name: "A", reputation: 0 };
  mockOnce({ token: "tok-123", user });
  const got = await login("a@x.com", "longenough");
  expect(got).toEqual(user);
  expect(getToken()).toBe("tok-123");
});

test("signup posts email+password+display_name and stores the token", async () => {
  const user = { id: "u2", email: "b@x.com", display_name: "B", reputation: 0 };
  const spy = mockOnce({ token: "tok-9", user }, 201);
  await signup("b@x.com", "longenough", "B");
  expect(getToken()).toBe("tok-9");
  const body = JSON.parse((spy.mock.calls[0][1] as RequestInit).body as string);
  expect(body).toEqual({ email: "b@x.com", password: "longenough", display_name: "B" });
});

test("login throws an ApiError on a 401 and leaves no token", async () => {
  mockOnce({ detail: "Invalid email or password." }, 401);
  await expect(login("a@x.com", "wrong")).rejects.toThrow("Invalid email or password.");
  expect(getToken()).toBeNull();
});

test("me returns null and clears the token on 401", async () => {
  localStorage.setItem("authToken", "stale");
  mockOnce({ detail: "Not signed in." }, 401);
  expect(await me()).toBeNull();
  expect(getToken()).toBeNull();
});

test("me returns null without calling fetch when there is no token", async () => {
  const spy = mockOnce({});
  expect(await me()).toBeNull();
  expect(spy).not.toHaveBeenCalled();
});

test("me attaches the bearer token and returns the user", async () => {
  localStorage.setItem("authToken", "tok-123");
  const user = { id: "u1", email: "a@x.com", display_name: "A", reputation: 5 };
  const spy = mockOnce(user);
  expect(await me()).toEqual(user);
  const headers = (spy.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
  expect(headers.Authorization).toBe("Bearer tok-123");
});

test("logout clears the token", async () => {
  localStorage.setItem("authToken", "tok-123");
  mockOnce(null, 204);
  await logout();
  expect(getToken()).toBeNull();
});
