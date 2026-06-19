import { expect, test } from "vitest";
import { notesToGeoJSON } from "./regionGeoJSON";
import type { NoteOut } from "../api/types";

const base = { author_id: "u", title: "t", lng: null, lat: null, sections: [], appends: [], editable: false };

test("builds Polygon + LineString features, skips point notes", () => {
  const notes = [
    { ...base, id: "a", shape: { kind: "polygon", coordinates: [[-71, 42], [-71, 43], [-70, 43], [-71, 42]] } },
    { ...base, id: "l", shape: { kind: "line", coordinates: [[-71, 42], [-70, 43]] } },
    { ...base, id: "p", lng: -71, lat: 42, shape: null },
  ] as NoteOut[];
  const fc = notesToGeoJSON(notes);
  expect(fc.features).toHaveLength(2);
  const poly = fc.features.find((f) => f.properties!.noteId === "a")!;
  expect(poly.geometry.type).toBe("Polygon");
  expect((poly.geometry as GeoJSON.Polygon).coordinates[0]).toHaveLength(4);
  const line = fc.features.find((f) => f.properties!.noteId === "l")!;
  expect(line.geometry.type).toBe("LineString");
});
