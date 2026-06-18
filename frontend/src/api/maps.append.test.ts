import { afterEach, expect, test, vi } from "vitest";
import { createAppend, updateAppend } from "./maps";

afterEach(() => vi.restoreAllMocks());
function spy(status = 200, body: unknown = { id: "a1", version: 2 }) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(() =>
    Promise.resolve(new Response(JSON.stringify(body), { status })),
  );
}

test("createAppend POSTs to the parent's appends with preview_as", async () => {
  const s = spy(201, { id: "a1" });
  await createAppend("n1", { title: "Tip", sections: [] }, "u1");
  const [url, init] = s.mock.calls[0];
  expect(url).toContain("/notes/n1/appends?preview_as=u1");
  expect(init).toMatchObject({ method: "POST" });
  expect(JSON.parse((init as RequestInit).body as string)).toMatchObject({ title: "Tip" });
});

test("updateAppend PUTs to /appends/{id} with the version", async () => {
  const s = spy(200, { id: "a1", version: 3 });
  await updateAppend("a1", { title: "", sections: [], version: 2 }, "u1");
  const [url, init] = s.mock.calls[0];
  expect(url).toContain("/appends/a1?preview_as=u1");
  expect(init).toMatchObject({ method: "PUT" });
  expect(JSON.parse((init as RequestInit).body as string)).toMatchObject({ version: 2 });
});
