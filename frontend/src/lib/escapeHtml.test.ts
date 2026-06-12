import { expect, test } from "vitest";
import { escapeHtml } from "./escapeHtml";

test("escapes the five HTML metacharacters", () => {
  expect(escapeHtml('<img src=x onerror="alert(1)">')).toBe(
    "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;",
  );
});

test("escapes ampersands without double-encoding the entities it emits", () => {
  expect(escapeHtml("Tom & Jerry < 5")).toBe("Tom &amp; Jerry &lt; 5");
});

test("leaves safe text unchanged", () => {
  expect(escapeHtml("Castle Island")).toBe("Castle Island");
});
