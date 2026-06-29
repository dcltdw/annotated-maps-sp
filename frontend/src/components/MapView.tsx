import maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import "maplibre-gl/dist/maplibre-gl.css";
import type { NoteOut } from "../api/types";
import { createShapeDrawer } from "../lib/draw";
import type { DrawMode, DrawShape, ShapeDrawer } from "../lib/draw";
import { escapeHtml } from "../lib/escapeHtml";
import { notesToGeoJSON } from "../lib/regionGeoJSON";
import { colorFor } from "../ruleColors";

interface Props {
  center: [number, number];
  zoom: number;
  notes: NoteOut[];
  onSelect: (noteId: string) => void;
  onMapClick?: (lng: number, lat: number) => void;
  onDraftMove?: (lng: number, lat: number) => void;
  draft?: [number, number] | null;
  // When non-null, MapView starts that draw via the ShapeDrawer port; null cancels any
  // in-progress draw. The completed shape is reported via onShapeDrawn.
  drawMode?: DrawMode | null;
  onShapeDrawn?: (shape: DrawShape) => void;
}

// User-controlled fields (title, content, group/rule labels) are HTML-escaped
// before being injected into the popup. colorFor() returns only fixed hex codes.
export function peekHtml(note: NoteOut): string {
  const rows = note.sections
    .map((s) => {
      const label = escapeHtml(s.rule_label);
      return s.visibility === "teaser"
        ? `<span style="color:${colorFor(s.rule_type)}">🔒 ${label}</span>${
            s.teaser_text ? " " + escapeHtml(s.teaser_text) : ""
          }`
        : `<span style="color:${colorFor(s.rule_type)}">● ${label}</span> ${escapeHtml(s.content ?? "")}`;
    })
    .join("<br>");
  return `<div style="font:13px system-ui;line-height:1.45;color:#111"><b>${escapeHtml(note.title)}</b><br>${rows}</div>`;
}

interface Placed {
  marker: maplibregl.Marker;
  popup: maplibregl.Popup;
}

/**
 * Renders the visibility-filtered notes as maplibre markers. `onSelect` should be
 * stable (wrap in useCallback in the parent) — it's an effect dep, so a fresh
 * reference each render re-places every marker.
 */
export function MapView({ center, zoom, notes, onSelect, onMapClick, onDraftMove, draft, drawMode, onShapeDrawn }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | undefined>(undefined);
  const markersRef = useRef<Placed[]>([]);
  const draftMarkerRef = useRef<maplibregl.Marker | undefined>(undefined);
  // The ShapeDrawer port (terra-draw adapter or a Fake) — built async after the map exists.
  const drawerRef = useRef<ShapeDrawer | null>(null);
  // Flips true once the drawer is mounted, so the draw-mode effect re-runs and can start a
  // draw requested before the async build finished.
  const [drawerReady, setDrawerReady] = useState(false);
  // Stable refs so the (once-only) effects' closures never go stale.
  const onMapClickRef = useRef(onMapClick);
  onMapClickRef.current = onMapClick;
  // Dragging the draft pin must work even after a click flips the screen into create
  // mode (at which point onMapClick is no longer passed) — so it has its own callback.
  const onDraftMoveRef = useRef(onDraftMove);
  onDraftMoveRef.current = onDraftMove;
  // Stable ref so the once-only region layer click handlers select via the latest onSelect.
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  // Stable ref so the draw effect hands the drawer the latest completion handler.
  const onShapeDrawnRef = useRef(onShapeDrawn);
  onShapeDrawnRef.current = onShapeDrawn;

  useEffect(() => {
    if (!ref.current) return;
    const map = new maplibregl.Map({
      container: ref.current,
      style: "https://tiles.openfreemap.org/styles/positron",
      center,
      zoom,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.on("click", (e: maplibregl.MapMouseEvent) => {
      onMapClickRef.current?.(e.lngLat.lng, e.lngLat.lat);
    });
    mapRef.current = map;
    // Expose the map for e2e assertions (never in production builds).
    if (import.meta.env.MODE !== "production") {
      (window as unknown as { __map?: maplibregl.Map }).__map = map;
    }
    return () => map.remove();
    // center/zoom only seed the initial view; the map is created once.
    // onMapClickRef is a stable ref; no need to list it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Build + mount the ShapeDrawer once the map exists. createShapeDrawer() is async, so
  // we run it in an IIFE and guard against the cleanup racing a still-in-flight build.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    let cancelled = false;
    // terra-draw's mount() calls map.addSource/addLayer, which throw "Style is not
    // done loading" if the style hasn't finished loading yet. Under production timing
    // the async build resolves before the style loads, the throw aborts setup, and the
    // whole map renders blank. Gate mount() on the style load — the same guard the
    // marker and region effects below use.
    (async () => {
      const drawer = await createShapeDrawer();
      if (cancelled) {
        drawer.destroy();
        return;
      }
      const mount = () => {
        if (cancelled) {
          drawer.destroy();
          return;
        }
        drawer.mount(map);
        drawerRef.current = drawer;
        setDrawerReady(true);
      };
      if (map.isStyleLoaded?.()) mount();
      else map.once("load", mount);
    })();
    return () => {
      cancelled = true;
      drawerRef.current?.destroy();
      drawerRef.current = null;
      setDrawerReady(false);
    };
    // mapRef is a stable ref; the drawer is built once alongside the map.
  }, []);

  // Draw-mode effect: a non-null drawMode starts that draw via the port; null cancels.
  // Re-runs on drawerReady too, so a draw requested before the async build finished still
  // starts. Uses the stable onShapeDrawnRef so the completion handler is never stale.
  useEffect(() => {
    const drawer = drawerRef.current;
    if (!drawer) return;
    if (drawMode) {
      drawer.startDraw(drawMode, (shape) => onShapeDrawnRef.current?.(shape));
    } else {
      drawer.cancel();
    }
    // onShapeDrawnRef is a stable ref; the effect reacts to drawMode/drawerReady.
  }, [drawMode, drawerReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const clear = () => {
      markersRef.current.forEach(({ marker, popup }) => {
        marker.remove();
        popup.remove();
      });
      markersRef.current = [];
    };
    const place = () => {
      clear();
      markersRef.current = notes
        .filter((n) => n.lng != null && n.lat != null)
        .map((n) => {
          const popup = new maplibregl.Popup({ offset: 20, closeButton: false }).setHTML(peekHtml(n));
          const marker = new maplibregl.Marker({ color: "#dc2626" })
            .setLngLat([n.lng as number, n.lat as number])
            .addTo(map);
          const el = marker.getElement();
          el.style.cursor = "pointer";
          el.addEventListener("mouseenter", () => popup.setLngLat([n.lng as number, n.lat as number]).addTo(map));
          el.addEventListener("mouseleave", () => popup.remove());
          el.addEventListener("click", () => onSelect(n.id));
          return { marker, popup };
        });
    };
    if (map.isStyleLoaded?.()) place();
    else map.on("load", place);
    // Deregister a pending load handler if the effect re-runs before the style loads
    // (e.g. Strict Mode double-invoke), so place() can't stack. Block body keeps the
    // cleanup's return void (map.off is chainable and returns the Map).
    return () => {
      map.off("load", place);
    };
  }, [notes, onSelect]);

  // Region effect: render area notes as a fill+outline and path notes as a line, kept in
  // sync with `notes` via setData; clicking a region selects it (same path as markers).
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const data = notesToGeoJSON(notes);
    const apply = () => {
      const existing = map.getSource("regions") as maplibregl.GeoJSONSource | undefined;
      if (existing) {
        existing.setData(data);
        return;
      }
      map.addSource("regions", { type: "geojson", data });
      map.addLayer({
        id: "regions-fill",
        type: "fill",
        source: "regions",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "fill-color": "#dc2626", "fill-opacity": 0.18 },
      });
      map.addLayer({
        id: "regions-outline",
        type: "line",
        source: "regions",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "line-color": "#dc2626", "line-width": 2 },
      });
      map.addLayer({
        id: "regions-line",
        type: "line",
        source: "regions",
        filter: ["==", ["geometry-type"], "LineString"],
        paint: { "line-color": "#dc2626", "line-width": 3 },
      });
      for (const layer of ["regions-fill", "regions-line"]) {
        map.on("click", layer, (e) => {
          const id = e.features?.[0]?.properties?.noteId;
          if (id) onSelectRef.current?.(String(id));
        });
        map.on("mouseenter", layer, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layer, () => {
          map.getCanvas().style.cursor = "";
        });
      }
    };
    if (map.isStyleLoaded?.()) apply();
    else map.once("load", apply);
    // mapRef/onSelectRef are stable refs; the source is re-synced whenever notes change.
  }, [notes]);

  // Draft-pin effect: add/remove/reposition ONE blue draggable marker for the pending create.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    // Remove any previous draft marker.
    if (draftMarkerRef.current) {
      draftMarkerRef.current.remove();
      draftMarkerRef.current = undefined;
    }
    if (!draft) return;
    const marker = new maplibregl.Marker({ color: "#2563eb", draggable: true })
      .setLngLat(draft)
      .addTo(map);
    marker.on("dragend", () => {
      const { lng, lat } = marker.getLngLat();
      onDraftMoveRef.current?.(lng, lat);
    });
    draftMarkerRef.current = marker;
    return () => {
      marker.remove();
      draftMarkerRef.current = undefined;
    };
  }, [draft]);

  return <div ref={ref} className="map" data-testid="map" />;
}
