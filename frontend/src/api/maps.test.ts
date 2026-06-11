import { afterEach, expect, test, vi } from "vitest";
import { fetchMaps, fetchNotes, fetchViewers } from "./maps";

afterEach(() => vi.restoreAllMocks());

function mockFetch(status = 200) {
  // Fresh Response per call — a Response body can only be read once.
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(() => Promise.resolve(new Response(JSON.stringify([]), { status })));
}

test("fetchNotes adds preview_as when given a viewer id", async () => {
  const spy = mockFetch();
  await fetchNotes("map-1", "user-9");
  expect(spy.mock.calls[0][0]).toContain("/maps/map-1/notes?preview_as=user-9");
});

test("fetchNotes omits preview_as for a guest", async () => {
  const spy = mockFetch();
  await fetchNotes("map-1", null);
  expect(spy.mock.calls[0][0]).not.toContain("preview_as");
});

test("fetchMaps and fetchViewers hit their endpoints", async () => {
  const spy = mockFetch();
  await fetchMaps();
  await fetchViewers("map-1");
  expect(spy.mock.calls[0][0]).toContain("/maps");
  expect(spy.mock.calls[1][0]).toContain("/maps/map-1/viewers");
});

test("getJson throws on a non-OK response", async () => {
  mockFetch(404);
  await expect(fetchMaps()).rejects.toThrow("404");
});
