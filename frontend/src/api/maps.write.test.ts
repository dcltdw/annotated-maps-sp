import { afterEach, expect, test, vi } from "vitest";
import { createNote, deleteNote, fetchGroups, updateNote } from "./maps";
import { clearToken, setToken } from "./auth";

afterEach(() => vi.restoreAllMocks());

function spy(status = 200, body: unknown = { id: "n1", version: 2 }) {
  // 204 No Content responses must have a null body per the WHATWG spec;
  // passing a non-null serialised body causes Response() to throw.
  const responseBody = status === 204 ? null : JSON.stringify(body);
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(() => Promise.resolve(new Response(responseBody, { status })));
}
const note = { title: "t", lng: -71, lat: 42, sections: [] };

test("createNote POSTs to the map's notes with preview_as", async () => {
  const s = spy(201, { id: "n1" });
  await createNote("m1", note, "u1");
  const [url, init] = s.mock.calls[0];
  expect(url).toContain("/maps/m1/notes?preview_as=u1");
  expect(init).toMatchObject({ method: "POST" });
  expect(JSON.parse((init as RequestInit).body as string)).toMatchObject({ title: "t" });
});

test("updateNote PUTs to the note with the version in the body", async () => {
  const s = spy(200, { id: "n1", version: 3 });
  await updateNote("n1", { ...note, version: 2 }, "u1");
  const [url, init] = s.mock.calls[0];
  expect(url).toContain("/notes/n1?preview_as=u1");
  expect(init).toMatchObject({ method: "PUT" });
  expect(JSON.parse((init as RequestInit).body as string)).toMatchObject({ version: 2 });
});

test("deleteNote DELETEs the note", async () => {
  const s = spy(204, null);
  await deleteNote("n1", "u1");
  expect(s.mock.calls[0][0]).toContain("/notes/n1?preview_as=u1");
  expect(s.mock.calls[0][1]).toMatchObject({ method: "DELETE" });
});

test("fetchGroups hits the groups endpoint", async () => {
  const s = spy(200, []);
  await fetchGroups("m1");
  expect(s.mock.calls[0][0]).toContain("/maps/m1/groups");
});

test("createNote attaches the bearer token when one is stored", async () => {
  setToken("tok-abc");
  const fetchSpy = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ id: "n1" }), { status: 201 })));
  await createNote("m1", { title: "T", lng: -71, lat: 42, sections: [] }, null);
  const init = fetchSpy.mock.calls[0][1] as RequestInit;
  expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-abc");
  expect(fetchSpy.mock.calls[0][0]).not.toContain("preview_as"); // null previewAs omits the param
  clearToken();
});

test("createNote omits Authorization when no token is stored", async () => {
  clearToken();
  const fetchSpy = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ id: "n1" }), { status: 201 })));
  await createNote("m1", { title: "T", lng: -71, lat: 42, sections: [] }, "owner");
  const init = fetchSpy.mock.calls[0][1] as RequestInit;
  expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  expect(fetchSpy.mock.calls[0][0]).toContain("preview_as=owner"); // string previewAs still sent
});
