import type { ShapeDrawer } from "./types";

export type { DrawMode, DrawShape, ShapeDrawer } from "./types";
export { FakeShapeDrawer } from "./FakeShapeDrawer";

declare global {
  interface Window {
    __shapeDrawerOverride?: ShapeDrawer;
  }
}

/** Build the app's ShapeDrawer. A non-production window override (set by e2e) wins,
 *  so tests can inject a FakeShapeDrawer without bundling/initialising terra-draw. */
export async function createShapeDrawer(): Promise<ShapeDrawer> {
  if (import.meta.env.MODE !== "production" && window.__shapeDrawerOverride) {
    return window.__shapeDrawerOverride;
  }
  const { TerraDrawAdapter } = await import("./TerraDrawAdapter");
  return new TerraDrawAdapter();
}
