import type { Map as MaplibreMap } from "maplibre-gl";

export type DrawMode = "polygon" | "line" | "circle";

/** Our geometry type — independent of any draw library. `circle` mode emits a `polygon`. */
export type DrawShape =
  | { kind: "polygon"; coordinates: [number, number][] } // outer ring [lng,lat]
  | { kind: "line"; coordinates: [number, number][] };

/** A swappable map-drawing port. Only adapters import a concrete draw library. */
export interface ShapeDrawer {
  mount(map: MaplibreMap): void;
  startDraw(mode: DrawMode, onComplete: (shape: DrawShape) => void): void;
  /** Reserved for in-place vertex editing. The current UI changes geometry by redrawing
   *  (startDraw), so no caller invokes this yet; the terra-draw adapter throws if called. */
  editShape(shape: DrawShape, onChange: (shape: DrawShape) => void): void;
  cancel(): void;
  destroy(): void;
}
