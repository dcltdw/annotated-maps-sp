import type { Map as MaplibreMap } from "maplibre-gl";
import {
  TerraDraw,
  TerraDrawPolygonMode,
  TerraDrawLineStringMode,
  TerraDrawCircleMode,
  TerraDrawRenderMode,
  type GeoJSONStoreFeatures,
} from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";
import type { DrawMode, DrawShape, ShapeDrawer } from "./types";

/** terra-draw mode name for an idle state that accepts no drawing input. */
const IDLE_MODE = "idle";

/** Map our DrawMode → terra-draw's built-in mode name. */
function toTerraMode(mode: DrawMode): string {
  switch (mode) {
    case "polygon":
      return "polygon";
    case "line":
      return "linestring";
    case "circle":
      return "circle";
  }
}

function asLngLat(coord: number[]): [number, number] {
  return [coord[0], coord[1]];
}

/** Convert a finished terra-draw feature into our library-independent DrawShape. */
function toDrawShape(feature: GeoJSONStoreFeatures): DrawShape | null {
  const geom = feature.geometry;
  // Circle mode emits a Polygon (a many-sided ring), so polygon + circle share this path.
  if (geom.type === "Polygon") {
    return { kind: "polygon", coordinates: geom.coordinates[0].map(asLngLat) };
  }
  if (geom.type === "LineString") {
    return { kind: "line", coordinates: geom.coordinates.map(asLngLat) };
  }
  return null;
}

/**
 * Real terra-draw implementation behind the ShapeDrawer port. This is the ONLY
 * file in the app allowed to import terra-draw; it is lazy-loaded via the factory.
 */
export class TerraDrawAdapter implements ShapeDrawer {
  private draw: TerraDraw | null = null;
  private finishHandler: ((id: string | number) => void) | null = null;

  mount(map: MaplibreMap): void {
    const adapter = new TerraDrawMapLibreGLAdapter({ map });
    this.draw = new TerraDraw({
      adapter,
      modes: [
        new TerraDrawPolygonMode(),
        new TerraDrawLineStringMode(),
        new TerraDrawCircleMode(),
        // A render-only mode used as an idle state: it accepts no drawing input.
        new TerraDrawRenderMode({ modeName: IDLE_MODE, styles: {} }),
      ],
    });
    this.draw.start();
    this.draw.setMode(IDLE_MODE);
  }

  startDraw(mode: DrawMode, onComplete: (shape: DrawShape) => void): void {
    const draw = this.draw;
    if (!draw) throw new Error("TerraDrawAdapter.startDraw called before mount");

    this.detachFinish();
    draw.setMode(toTerraMode(mode));

    const handler = (id: string | number) => {
      const feature = draw.getSnapshotFeature(id);
      if (!feature) return;
      const shape = toDrawShape(feature);
      // Settle to idle and clear terra-draw's copy; the saved note renders via
      // the app's own regions layers, so terra-draw must not keep the feature.
      this.detachFinish();
      draw.setMode(IDLE_MODE);
      draw.clear();
      if (shape) onComplete(shape);
    };
    this.finishHandler = handler;
    draw.on("finish", handler);
  }

  /** Editing is deferred to redraw-to-change (allowed by the spec). */
  editShape(_shape: DrawShape, _onChange: (shape: DrawShape) => void): void {
    throw new Error("edit via redraw");
  }

  cancel(): void {
    const draw = this.draw;
    if (!draw) return;
    this.detachFinish();
    draw.setMode(IDLE_MODE);
    draw.clear();
  }

  destroy(): void {
    if (!this.draw) return;
    this.detachFinish();
    this.draw.stop();
    this.draw = null;
  }

  private detachFinish(): void {
    if (this.draw && this.finishHandler) {
      this.draw.off("finish", this.finishHandler);
    }
    this.finishHandler = null;
  }
}
