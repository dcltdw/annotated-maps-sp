import { fireEvent, render } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

const { Marker, Popup, MapCtor, markerEls } = vi.hoisted(() => {
  // Each Marker gets its own DOM element so tests can dispatch events at a specific marker.
  const markerEls: HTMLElement[] = [];
  const Marker = vi.fn(function () {
    const el = document.createElement("div");
    markerEls.push(el);
    return {
      setLngLat: vi.fn().mockReturnThis(),
      addTo: vi.fn().mockReturnThis(),
      getElement: () => el,
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
  // on("load", cb) fires immediately; isStyleLoaded is absent so the component takes the load path.
  const map = {
    addControl: vi.fn(),
    on: vi.fn(function (ev: string, cb: () => void) {
      if (ev === "load") cb();
    }),
    off: vi.fn(),
    remove: vi.fn(),
  };
  const MapCtor = vi.fn(function () {
    return map;
  });
  return { Marker, Popup, MapCtor, markerEls };
});
vi.mock("maplibre-gl", () => ({
  default: { Map: MapCtor, Marker, Popup, NavigationControl: vi.fn(function () { return {}; }) },
}));

import { MapView, peekHtml } from "./MapView";
import type { NoteOut } from "../api/types";

afterEach(() => {
  vi.clearAllMocks();
  markerEls.length = 0;
});

const notes: NoteOut[] = [
  { id: "n1", title: "A", lng: -71, lat: 42, sections: [] },
  { id: "n2", title: "B", lng: -71.1, lat: 42.1, sections: [] },
];

test("adds a marker per note", () => {
  render(<MapView center={[-71, 42]} zoom={12} notes={notes} onSelect={() => {}} />);
  expect(Marker).toHaveBeenCalledTimes(2);
});

test("skips notes without coordinates", () => {
  const withNull: NoteOut[] = [...notes, { id: "n3", title: "C", lng: null, lat: null, sections: [] }];
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

test("peekHtml escapes user-controlled note fields", () => {
  const html = peekHtml({
    id: "x",
    title: "<b>pwn</b>",
    lng: 0,
    lat: 0,
    sections: [
      { id: "s", order: 0, visibility: "visible", content: "<script>", rule_type: "public", rule_label: "<i>lbl</i>" },
    ],
  });
  expect(html).not.toContain("<b>pwn</b>"); // title
  expect(html).not.toContain("<script>"); // content
  expect(html).not.toContain("<i>lbl</i>"); // rule_label
  expect(html).toContain("&lt;script&gt;");
  expect(html).toContain("&lt;i&gt;lbl&lt;/i&gt;");
});
