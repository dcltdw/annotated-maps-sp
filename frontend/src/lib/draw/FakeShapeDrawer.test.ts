import { expect, test, vi } from "vitest";
import { FakeShapeDrawer } from "./FakeShapeDrawer";
import type { DrawShape } from "./types";

test("startDraw records the mode and emits the shape to onComplete", () => {
  const d = new FakeShapeDrawer();
  const onComplete = vi.fn();
  d.startDraw("polygon", onComplete);
  expect(d.lastMode).toBe("polygon");
  const shape: DrawShape = { kind: "polygon", coordinates: [[-71, 42], [-71, 43], [-70, 43], [-71, 42]] };
  d.emit(shape);
  expect(onComplete).toHaveBeenCalledWith(shape);
});

test("cancel clears the pending completion handler", () => {
  const d = new FakeShapeDrawer();
  const onComplete = vi.fn();
  d.startDraw("polygon", onComplete);
  d.cancel();
  d.emit({ kind: "polygon", coordinates: [[0, 0], [0, 1], [1, 1], [0, 0]] });
  expect(onComplete).not.toHaveBeenCalled();
});
