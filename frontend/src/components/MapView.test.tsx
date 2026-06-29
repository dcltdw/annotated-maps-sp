import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FakeShapeDrawer } from "../lib/draw";

const { Marker, Popup, MapCtor, markerEls, capturedHandlers } = vi.hoisted(() => {
  // Each Marker gets its own DOM element so tests can dispatch events at a specific marker.
  const markerEls: HTMLElement[] = [];
  const Marker = vi.fn(function () {
    const el = document.createElement("div");
    markerEls.push(el);
    return {
      setLngLat: vi.fn().mockReturnThis(),
      addTo: vi.fn().mockReturnThis(),
      getElement: () => el,
      getLngLat: vi.fn().mockReturnValue({ lng: -71, lat: 42 }),
      on: vi.fn(),
      remove: vi.fn(),
    };
  });
  const Popup = vi.fn(function () {
    return {
      setHTML: vi.fn().mockReturnThis(),
      setLngLat: vi.fn().mockReturnThis(),
      addTo: vi.fn().mockReturnThis(),
      remove: vi.fn(),
    };
  });
  // Capture all registered handlers so tests can fire them manually.
  const capturedHandlers: Record<string, ((...args: unknown[]) => void)[]> = {};
  // on/once("load", cb) fire immediately so the marker + region effects run apply()
  // synchronously. isStyleLoaded is absent so both effects take the load path. The
  // region source/layer methods are stubbed so the region effect's apply() doesn't throw.
  const map = {
    addControl: vi.fn(),
    on: vi.fn(function (ev: string, ...rest: unknown[]) {
      // Marker/map handlers register as on(ev, cb); region layer handlers register as
      // on(ev, layerId, cb) — the callback is always the LAST argument.
      const cb = rest[rest.length - 1] as (...args: unknown[]) => void;
      if (!capturedHandlers[ev]) capturedHandlers[ev] = [];
      capturedHandlers[ev].push(cb);
      if (ev === "load") cb();
    }),
    once: vi.fn(function (ev: string, cb: (...args: unknown[]) => void) {
      if (ev === "load") cb();
    }),
    off: vi.fn(),
    remove: vi.fn(),
    getSource: vi.fn().mockReturnValue(undefined),
    addSource: vi.fn(),
    addLayer: vi.fn(),
    // The map click handler guards pin-creation by checking whether the click hit a
    // region/route feature; with no layers present it falls through to onMapClick.
    getLayer: vi.fn().mockReturnValue(undefined),
    queryRenderedFeatures: vi.fn().mockReturnValue([]),
    getCanvas: vi.fn().mockReturnValue({ style: {} }),
  };
  const MapCtor = vi.fn(function () {
    return map;
  });
  return { Marker, Popup, MapCtor, markerEls, capturedHandlers };
});
vi.mock("maplibre-gl", () => ({
  default: { Map: MapCtor, Marker, Popup, NavigationControl: vi.fn(function () { return {}; }) },
}));

import { MapView, peekHtml } from "./MapView";
import type { NoteOut } from "../api/types";

// Inject a FakeShapeDrawer so the createShapeDrawer() factory returns it (non-prod window
// override) — keeps MapView's drawer wiring WebGL-free and never loads real terra-draw.
let fakeDrawer: FakeShapeDrawer;
beforeEach(() => {
  fakeDrawer = new FakeShapeDrawer();
  window.__shapeDrawerOverride = fakeDrawer;
});

afterEach(() => {
  vi.clearAllMocks();
  markerEls.length = 0;
  delete window.__shapeDrawerOverride;
  // Clear captured handlers between tests
  Object.keys(capturedHandlers).forEach((k) => delete capturedHandlers[k]);
});

const notes: NoteOut[] = [
  { id: "n1", author_id: "u1", title: "A", lng: -71, lat: 42, editable: false, sections: [], appends: [], shape: null },
  { id: "n2", author_id: "u1", title: "B", lng: -71.1, lat: 42.1, editable: false, sections: [], appends: [], shape: null },
];

test("adds a marker per note", () => {
  render(<MapView center={[-71, 42]} zoom={12} notes={notes} onSelect={() => {}} />);
  expect(Marker).toHaveBeenCalledTimes(2);
});

test("skips notes without coordinates", () => {
  const withNull: NoteOut[] = [...notes, { id: "n3", author_id: "u1", title: "C", lng: null, lat: null, editable: false, sections: [], appends: [], shape: null }];
  render(<MapView center={[-71, 42]} zoom={12} notes={withNull} onSelect={() => {}} />);
  expect(Marker).toHaveBeenCalledTimes(2);
});

test("clicking a marker calls onSelect with the note id", () => {
  const onSelect = vi.fn();
  render(<MapView center={[-71, 42]} zoom={12} notes={[notes[0]]} onSelect={onSelect} />);
  fireEvent.click(markerEls[0]);
  expect(onSelect).toHaveBeenCalledWith("n1");
});

test("hovering a marker shows its popup and leaving removes it", () => {
  render(<MapView center={[-71, 42]} zoom={12} notes={[notes[0]]} onSelect={() => {}} />);
  const popup = Popup.mock.results[0].value;
  fireEvent.mouseEnter(markerEls[0]);
  expect(popup.addTo).toHaveBeenCalled();
  fireEvent.mouseLeave(markerEls[0]);
  expect(popup.remove).toHaveBeenCalled();
});

test("map click fires onMapClick with lngLat", () => {
  const onMapClick = vi.fn();
  render(<MapView center={[-71, 42]} zoom={12} notes={[]} onSelect={() => {}} onMapClick={onMapClick} />);
  // Fire the captured "click" handler with a mock MapMouseEvent
  const [clickHandler] = capturedHandlers["click"] ?? [];
  expect(clickHandler).toBeDefined();
  clickHandler({ lngLat: { lng: -71.5, lat: 42.3 } });
  expect(onMapClick).toHaveBeenCalledWith(-71.5, 42.3);
});

test("passing a draft creates one extra Marker (blue draft pin)", () => {
  render(
    <MapView
      center={[-71, 42]}
      zoom={12}
      notes={notes}
      onSelect={() => {}}
      draft={[-71.2, 42.2]}
    />,
  );
  // 2 note markers + 1 draft marker = 3
  expect(Marker).toHaveBeenCalledTimes(3);
});

test("dragging the draft pin reports the new position via onDraftMove", () => {
  const onDraftMove = vi.fn();
  render(
    <MapView center={[-71, 42]} zoom={12} notes={[]} onSelect={() => {}} draft={[-71.2, 42.2]} onDraftMove={onDraftMove} />,
  );
  // notes=[] → the only Marker created is the draft pin; grab its dragend handler.
  const draftMarker = Marker.mock.results[0].value;
  const dragend = draftMarker.on.mock.calls.find((c: unknown[]) => c[0] === "dragend")?.[1] as
    | (() => void)
    | undefined;
  expect(dragend).toBeDefined();
  dragend?.();
  // the mock marker's getLngLat() returns { lng: -71, lat: 42 }
  expect(onDraftMove).toHaveBeenCalledWith(-71, 42);
});

test("peekHtml escapes user-controlled note fields", () => {
  const html = peekHtml({
    id: "x",
    author_id: "u1",
    title: "<b>pwn</b>",
    lng: 0,
    lat: 0,
    editable: false,
    sections: [
      { id: "s", order: 0, visibility: "visible", content: "<script>", rule_type: "public", rule_label: "<i>lbl</i>", teaser_text: null },
    ],
    appends: [],
    shape: null,
  });
  expect(html).not.toContain("<b>pwn</b>"); // title
  expect(html).not.toContain("<script>"); // content
  expect(html).not.toContain("<i>lbl</i>"); // rule_label
  expect(html).toContain("&lt;script&gt;");
  expect(html).toContain("&lt;i&gt;lbl&lt;/i&gt;");
});

test("a non-null drawMode starts that draw via the ShapeDrawer port", async () => {
  render(<MapView center={[-71, 42]} zoom={12} notes={[]} onSelect={() => {}} drawMode="polygon" />);
  // The drawer is built async; wait for startDraw to record the requested mode.
  await waitFor(() => expect(fakeDrawer.lastMode).toBe("polygon"));
});

test("finishing a shape reports it via onShapeDrawn", async () => {
  const onShapeDrawn = vi.fn();
  render(
    <MapView center={[-71, 42]} zoom={12} notes={[]} onSelect={() => {}} drawMode="polygon" onShapeDrawn={onShapeDrawn} />,
  );
  await waitFor(() => expect(fakeDrawer.lastMode).toBe("polygon"));
  const shape = { kind: "polygon" as const, coordinates: [[-71, 42], [-71, 43], [-72, 43]] as [number, number][] };
  fakeDrawer.emit(shape);
  expect(onShapeDrawn).toHaveBeenCalledWith(shape);
});

test("peekHtml escapes a teaser section's teaser_text hook", () => {
  const html = peekHtml({
    id: "x",
    author_id: "u1",
    title: "Spot",
    lng: 0,
    lat: 0,
    editable: false,
    sections: [
      { id: "s", order: 0, visibility: "teaser", content: null, rule_type: "audience", rule_label: "Club", teaser_text: "<img onerror=1>" },
    ],
    appends: [],
    shape: null,
  });
  expect(html).not.toContain("<img onerror=1>");
  expect(html).toContain("&lt;img onerror=1&gt;");
});
