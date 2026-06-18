import { fireEvent, render } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

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
  // on("load", cb) fires immediately; isStyleLoaded is absent so the component takes the load path.
  const map = {
    addControl: vi.fn(),
    on: vi.fn(function (ev: string, cb: (...args: unknown[]) => void) {
      if (!capturedHandlers[ev]) capturedHandlers[ev] = [];
      capturedHandlers[ev].push(cb);
      if (ev === "load") cb();
    }),
    off: vi.fn(),
    remove: vi.fn(),
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

afterEach(() => {
  vi.clearAllMocks();
  markerEls.length = 0;
  // Clear captured handlers between tests
  Object.keys(capturedHandlers).forEach((k) => delete capturedHandlers[k]);
});

const notes: NoteOut[] = [
  { id: "n1", author_id: "u1", title: "A", lng: -71, lat: 42, sections: [], appends: [] },
  { id: "n2", author_id: "u1", title: "B", lng: -71.1, lat: 42.1, sections: [], appends: [] },
];

test("adds a marker per note", () => {
  render(<MapView center={[-71, 42]} zoom={12} notes={notes} onSelect={() => {}} />);
  expect(Marker).toHaveBeenCalledTimes(2);
});

test("skips notes without coordinates", () => {
  const withNull: NoteOut[] = [...notes, { id: "n3", author_id: "u1", title: "C", lng: null, lat: null, sections: [], appends: [] }];
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
    sections: [
      { id: "s", order: 0, visibility: "visible", content: "<script>", rule_type: "public", rule_label: "<i>lbl</i>", teaser_text: null },
    ],
    appends: [],
  });
  expect(html).not.toContain("<b>pwn</b>"); // title
  expect(html).not.toContain("<script>"); // content
  expect(html).not.toContain("<i>lbl</i>"); // rule_label
  expect(html).toContain("&lt;script&gt;");
  expect(html).toContain("&lt;i&gt;lbl&lt;/i&gt;");
});

test("peekHtml escapes a teaser section's teaser_text hook", () => {
  const html = peekHtml({
    id: "x",
    author_id: "u1",
    title: "Spot",
    lng: 0,
    lat: 0,
    sections: [
      { id: "s", order: 0, visibility: "teaser", content: null, rule_type: "audience", rule_label: "Club", teaser_text: "<img onerror=1>" },
    ],
    appends: [],
  });
  expect(html).not.toContain("<img onerror=1>");
  expect(html).toContain("&lt;img onerror=1&gt;");
});
