import maplibregl from "maplibre-gl";
import { useEffect, useRef } from "react";
import "maplibre-gl/dist/maplibre-gl.css";
import type { NoteOut } from "../api/types";
import { escapeHtml } from "../lib/escapeHtml";
import { colorFor } from "../ruleColors";

interface Props {
  center: [number, number];
  zoom: number;
  notes: NoteOut[];
  onSelect: (noteId: string) => void;
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
export function MapView({ center, zoom, notes, onSelect }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | undefined>(undefined);
  const markersRef = useRef<Placed[]>([]);

  useEffect(() => {
    if (!ref.current) return;
    const map = new maplibregl.Map({
      container: ref.current,
      style: "https://tiles.openfreemap.org/styles/positron",
      center,
      zoom,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    mapRef.current = map;
    return () => map.remove();
    // center/zoom only seed the initial view; deps intentionally empty (the map is created once).
  }, []);

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

  return <div ref={ref} className="map" data-testid="map" />;
}
