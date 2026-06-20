import type { Map as MaplibreMap } from "maplibre-gl";
import type { DrawMode, DrawShape, ShapeDrawer } from "./types";

/** Placeholder — real terra-draw integration lands in Task 2. */
export class TerraDrawAdapter implements ShapeDrawer {
  mount(_map: MaplibreMap): void {}
  startDraw(_mode: DrawMode, _onComplete: (s: DrawShape) => void): void {
    throw new Error("TerraDrawAdapter not implemented yet (A2.2b Task 2)");
  }
  editShape(_shape: DrawShape, _onChange: (s: DrawShape) => void): void {
    throw new Error("not implemented");
  }
  cancel(): void {}
  destroy(): void {}
}
