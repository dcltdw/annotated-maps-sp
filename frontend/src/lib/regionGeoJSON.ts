import type { FeatureCollection } from "geojson";
import type { NoteOut } from "../api/types";

/** Turn notes with an area/path shape into a GeoJSON FeatureCollection for maplibre.
 *  Point notes (shape === null) are rendered as markers elsewhere and skipped here. */
export function notesToGeoJSON(notes: NoteOut[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: notes
      .filter((n) => n.shape !== null)
      .map((n) => ({
        type: "Feature",
        properties: { noteId: n.id, kind: n.shape!.kind },
        geometry:
          n.shape!.kind === "polygon"
            ? { type: "Polygon", coordinates: [n.shape!.coordinates] }
            : { type: "LineString", coordinates: n.shape!.coordinates },
      })),
  };
}
