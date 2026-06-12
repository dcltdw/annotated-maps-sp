import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchMaps, fetchNotes, fetchViewers } from "./api/maps";
import type { MapOut, NoteOut, Viewer } from "./api/types";
import { MapView } from "./components/MapView";
import { NotePanel } from "./components/NotePanel";
import { PreviewSwitcher } from "./components/PreviewSwitcher";

export function MapScreen() {
  const [map, setMap] = useState<MapOut | null>(null);
  const [viewers, setViewers] = useState<Viewer[]>([]);
  const [previewAs, setPreviewAs] = useState<string | null>(null);
  const [notes, setNotes] = useState<NoteOut[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const { t } = useTranslation();

  useEffect(() => {
    fetchMaps()
      .then((maps) => {
        const m = maps[0] ?? null;
        setMap(m);
        if (m) fetchViewers(m.id).then(setViewers).catch(() => setViewers([]));
        else setLoadError(true);
      })
      .catch(() => setLoadError(true));
  }, []);

  useEffect(() => {
    if (!map) return;
    // Guard against a slow earlier fetch resolving after a faster later one when the
    // viewer is switched quickly — only the latest request may set state.
    let active = true;
    fetchNotes(map.id, previewAs)
      .then((ns) => {
        if (active) setNotes(ns);
      })
      .catch(() => {
        if (active) setNotes([]); // fail visible-empty rather than showing a stale slice
      });
    return () => {
      active = false;
    };
  }, [map, previewAs]);

  const selected = useMemo(() => notes.find((n) => n.id === selectedId) ?? null, [notes, selectedId]);
  const viewerLabel = previewAs
    ? viewers.find((v) => v.id === previewAs)?.display_name ?? t("switcher.viewer")
    : t("switcher.guest");

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
    setPanelOpen(true);
  }, []);

  if (loadError) return <p className="loading">{t("screen.error")}</p>;
  if (!map) return <p className="loading">{t("screen.loading")}</p>;

  return (
    <div className="screen">
      <header className="topbar">
        <strong>{t("app.title")} · {map.name}</strong>
        <PreviewSwitcher viewers={viewers} current={previewAs} onChange={setPreviewAs} />
      </header>
      <div className="stage">
        <div className="map-wrap">
          <MapView
            center={[map.lng, map.lat]}
            zoom={map.zoom}
            notes={notes}
            onSelect={handleSelect}
          />
          {selected && !panelOpen && (
            <button className="reopen" aria-label={t("screen.reopenAria")} onClick={() => setPanelOpen(true)}>
              {t("screen.reopen")}
            </button>
          )}
        </div>
        {selected && panelOpen && (
          <NotePanel note={selected} viewerLabel={viewerLabel} onCollapse={() => setPanelOpen(false)} />
        )}
      </div>
    </div>
  );
}
