import { describe, expect, it } from "vitest";
import { TerraDrawAdapter } from "./TerraDrawAdapter";

// Construct-smoke only: guards the terra-draw import/wiring. We do NOT call
// mount() here — that needs a real WebGL map, which jsdom cannot provide.
describe("TerraDrawAdapter", () => {
  it("constructs without throwing", () => {
    expect(() => new TerraDrawAdapter()).not.toThrow();
  });
});
