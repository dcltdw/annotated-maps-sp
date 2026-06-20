import type { DrawMode, DrawShape, ShapeDrawer } from "./types";

/** Test double: drives onComplete/onChange synchronously via emit(); no map/WebGL needed. */
export class FakeShapeDrawer implements ShapeDrawer {
  lastMode: DrawMode | null = null;
  private onComplete: ((s: DrawShape) => void) | null = null;

  mount(): void {}
  startDraw(mode: DrawMode, onComplete: (s: DrawShape) => void): void {
    this.lastMode = mode;
    this.onComplete = onComplete;
  }
  editShape(_shape: DrawShape, _onChange: (s: DrawShape) => void): void {}
  cancel(): void {
    this.onComplete = null;
  }
  destroy(): void {
    this.onComplete = null;
  }
  /** Test helper — simulate the user finishing a shape. */
  emit(shape: DrawShape): void {
    this.onComplete?.(shape);
  }
}
