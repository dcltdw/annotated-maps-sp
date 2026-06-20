import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ApiError } from "./api/maps";
import { createAppend, createNote, deleteNote, fetchGroups, fetchMaps, fetchNoteForEdit, fetchNotes, fetchViewers, updateAppend, updateNote } from "./api/maps";
import type { AppendInput, AppendUpdateInput, Group, MapOut, NoteEdit, NoteInput, NoteOut, NoteUpdateInput, Shape, Viewer } from "./api/types";
import type { DrawMode, DrawShape } from "./lib/draw";
import { NoteEditor } from "./components/NoteEditor";
import { NotePanel } from "./components/NotePanel";
import { PreviewSwitcher } from "./components/PreviewSwitcher";

// Lazy so maplibre-gl splits into its own chunk, loaded only when the map screen mounts.
const MapView = lazy(() => import("./components/MapView").then((m) => ({ default: m.MapView })));

type Mode = "view" | "create" | "edit" | "append" | "edit-append";

export function MapScreen() {
  const [map, setMap] = useState<MapOut | null>(null);
  const [viewers, setViewers] = useState<Viewer[]>([]);
  const [previewAs, setPreviewAs] = useState<string | null>(null);
  const [notes, setNotes] = useState<NoteOut[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const [loadError, setLoadError] = useState(false);

  // Write-mode state
  const [mode, setMode] = useState<Mode>("view");
  const [draft, setDraft] = useState<[number, number] | null>(null);
  const [editing, setEditing] = useState<NoteEdit | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [appendParent, setAppendParent] = useState<NoteOut | null>(null);

  // Draw-area state: drawMode drives MapView's ShapeDrawer; pendingShape holds the polygon
  // captured on completion, then feeds the editor (create) or replaces an editing region.
  const [drawMode, setDrawMode] = useState<DrawMode | null>(null);
  const [pendingShape, setPendingShape] = useState<DrawShape | null>(null);

  const { t } = useTranslation();

  useEffect(() => {
    fetchMaps()
      .then((maps) => {
        const m = maps[0] ?? null;
        setMap(m);
        if (m) {
          fetchViewers(m.id).then(setViewers).catch(() => setViewers([]));
          fetchGroups(m.id).then(setGroups).catch(() => setGroups([]));
        } else setLoadError(true);
      })
      .catch(() => setLoadError(true));
  }, []);

  // Single guarded notes loader, shared by the initial/persona-switch effect AND the
  // post-write reloads. A monotonic request id ensures only the latest fetch may set
  // state, so a slow reload (e.g. right after a save) can't clobber a newer
  // persona-switch fetch. Failures fail visible-empty rather than show a stale slice.
  const notesReqRef = useRef(0);
  const loadNotes = useCallback(() => {
    if (!map) return;
    const reqId = ++notesReqRef.current;
    fetchNotes(map.id, previewAs)
      .then((ns) => {
        if (reqId === notesReqRef.current) setNotes(ns);
      })
      .catch(() => {
        if (reqId === notesReqRef.current) setNotes([]);
      });
  }, [map, previewAs]);

  useEffect(() => {
    loadNotes();
  }, [loadNotes]);

  const selected = useMemo(() => notes.find((n) => n.id === selectedId) ?? null, [notes, selectedId]);
  const viewerLabel = previewAs
    ? viewers.find((v) => v.id === previewAs)?.display_name ?? t("switcher.viewer")
    : t("switcher.guest");

  const canWrite = previewAs !== null;

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
    setPanelOpen(true);
  }, []);

  const handleMapClick = useCallback((lng: number, lat: number) => {
    if (!canWrite || mode !== "view") return;
    setDraft([lng, lat]);
    setMode("create");
    setSelectedId(null);
  }, [canWrite, mode]);

  // Dragging the draft pin repositions the pending note (no mode guard — only fires
  // while a draft pin exists, i.e. already in create mode).
  const handleDraftMove = useCallback((lng: number, lat: number) => {
    setDraft([lng, lat]);
  }, []);

  const resetToView = useCallback(() => {
    setMode("view");
    setDraft(null);
    setEditing(null);
    setError(null);
    setAppendParent(null);
    setDrawMode(null);
    setPendingShape(null);
  }, []);

  // Enter draw mode: arm the polygon drawer; stay in "view" so the map/markers keep
  // rendering. Suppress click-to-drop while drawing (see onMapClick gating below).
  const handleStartDraw = useCallback(() => {
    if (!canWrite) return;
    setSelectedId(null);
    setPendingShape(null);
    setDrawMode("polygon");
  }, [canWrite]);

  // Polygon finished: capture it, stop drawing. In create flow this opens the editor;
  // in region-edit (redraw) flow `editing` is already set and we just swap its shape.
  const handleShapeDrawn = useCallback((shape: DrawShape) => {
    setDrawMode(null);
    setPendingShape(shape);
    if (mode !== "edit") setMode("create");
  }, [mode]);

  const handleSave = useCallback(async (note: NoteInput | NoteUpdateInput) => {
    if (!map || !previewAs) return;
    try {
      if (mode === "create") {
        await createNote(map.id, note as NoteInput, previewAs);
      } else if (mode === "edit" && editing) {
        await updateNote(editing.id, note as NoteUpdateInput, previewAs);
      } else if (mode === "append" && appendParent) {
        await createAppend(appendParent.id, { title: (note as NoteInput).title, sections: (note as NoteInput).sections } as AppendInput, previewAs);
      } else if (mode === "edit-append" && editing) {
        await updateAppend(editing.id, { title: (note as NoteUpdateInput).title, sections: (note as NoteUpdateInput).sections, version: editing.version } as AppendUpdateInput, previewAs);
      }
      resetToView();
      loadNotes();
    } catch (e) {
      if ((e as ApiError).status === 409) {
        setError(t("editor.conflict"));
      } else if ((e as ApiError).status === 429) {
        setError((e as ApiError).message || t("editor.sandboxLimit"));
      } else {
        setError(t("editor.saveFailed"));
      }
    }
  }, [map, previewAs, mode, editing, appendParent, resetToView, loadNotes, t]);

  const handleEdit = useCallback(async () => {
    if (!selected || !previewAs) return;
    try {
      const noteEdit = await fetchNoteForEdit(selected.id, previewAs);
      setEditing(noteEdit);
      setMode("edit");
    } catch {
      setError(t("editor.loadFailed"));
    }
  }, [selected, previewAs, t]);

  const handleDelete = useCallback(async () => {
    if (!selected || !previewAs) return;
    try {
      await deleteNote(selected.id, previewAs);
      setSelectedId(null);
      loadNotes();
    } catch {
      setError(t("editor.deleteFailed"));
    }
  }, [selected, previewAs, loadNotes, t]);

  const handleAppend = useCallback(() => {
    if (!selected || !previewAs) return; // non-guest only (UI already gates ＋Append)
    setAppendParent(selected);
    setMode("append");
  }, [selected, previewAs]);

  const handleEditAppend = useCallback(async (appendId: string) => {
    if (!selected || !previewAs) return;
    try {
      const ed = await fetchNoteForEdit(appendId, previewAs);
      setAppendParent(selected);
      setEditing(ed);
      setMode("edit-append");
    } catch {
      setError(t("editor.loadFailed"));
    }
  }, [selected, previewAs, t]);

  const handleDeleteAppend = useCallback(async (appendId: string) => {
    if (!previewAs) return;
    try {
      await deleteNote(appendId, previewAs);
      loadNotes();
    } catch {
      setError(t("editor.deleteFailed"));
    }
  }, [previewAs, loadNotes, t]);

  if (loadError) return <p className="loading">{t("screen.error")}</p>;
  if (!map) return <p className="loading">{t("screen.loading")}</p>;

  // Coordinates for the editor: edit uses the stored note's coords, create uses the draft pin.
  const editorLng = mode === "edit" ? (editing?.lng ?? map.lng) : (draft?.[0] ?? map.lng);
  const editorLat = mode === "edit" ? (editing?.lat ?? map.lat) : (draft?.[1] ?? map.lat);

  // Editing requires both server-granted ownership AND a selected persona — acting as
  // Guest can't write, so we don't show an edit affordance that would dead-click.
  const canEdit = (selected?.editable ?? false) && canWrite;

  const editorVariant = mode === "append" || mode === "edit-append" ? "append" : "note";

  // Shape anchor for the editor (region notes). Create uses the freshly-drawn pendingShape;
  // edit uses a redraw (pendingShape) if any, else the loaded note's shape. When this is set
  // the editor emits a shape-anchored payload (and ignores lng/lat). Appends carry neither.
  const editorShape: Shape | undefined =
    editorVariant === "append"
      ? undefined
      : mode === "create"
        ? (pendingShape ?? undefined)
        : (pendingShape ?? editing?.shape ?? undefined);

  // Region edit (incl. a just-finished redraw) shows a "Redraw area" button.
  const isRegionEdit = mode === "edit" && editorShape != null;

  const editorPanel = mode !== "view" ? (
    <>
      {isRegionEdit && (
        <button type="button" className="redraw-area" onClick={handleStartDraw}>
          {t("screen.redrawArea")}
        </button>
      )}
      <NoteEditor
        lng={editorLng}
        lat={editorLat}
        shape={editorShape}
        groups={groups}
        authorLabel={viewerLabel}
        existing={editing ?? undefined}
        variant={editorVariant}
        onSave={handleSave}
        onCancel={resetToView}
      />
    </>
  ) : null;

  return (
    <div className="screen">
      {import.meta.env.VITE_SANDBOX === "true" && (
        <div className="sandbox-banner">{t("sandbox.banner")}</div>
      )}
      <header className="topbar">
        <strong>{t("app.title")} · {map.name}</strong>
        <PreviewSwitcher viewers={viewers} current={previewAs} onChange={setPreviewAs} />
      </header>
      {error && (
        <div className="editor-error-banner" role="alert">
          {error}
          <button type="button" onClick={() => setError(null)}>✕</button>
        </div>
      )}
      <div className="stage">
        <div className="map-wrap">
          <Suspense fallback={<div className="map" />}>
            <MapView
              center={[map.lng, map.lat]}
              zoom={map.zoom}
              notes={notes}
              onSelect={handleSelect}
              onMapClick={canWrite && mode === "view" && !drawMode ? handleMapClick : undefined}
              onDraftMove={handleDraftMove}
              draft={mode === "create" ? draft : null}
              drawMode={drawMode}
              onShapeDrawn={handleShapeDrawn}
            />
          </Suspense>
          {canWrite && mode === "view" && !drawMode && (
            <button className="draw-area" onClick={handleStartDraw}>
              {t("screen.drawArea")}
            </button>
          )}
          {drawMode && (
            <div className="drawing-hint" role="status">{t("screen.drawingHint")}</div>
          )}
          {selected && !panelOpen && mode === "view" && !drawMode && (
            <button className="reopen" aria-label={t("screen.reopenAria")} onClick={() => setPanelOpen(true)}>
              {t("screen.reopen")}
            </button>
          )}
        </div>
        {mode !== "view" && editorPanel}
        {mode === "view" && selected && panelOpen && (
          <NotePanel
            note={selected}
            viewerLabel={viewerLabel}
            onCollapse={() => setPanelOpen(false)}
            canEdit={canEdit}
            onEdit={handleEdit}
            onDelete={handleDelete}
            previewAs={previewAs}
            onAppend={handleAppend}
            onEditAppend={handleEditAppend}
            onDeleteAppend={handleDeleteAppend}
          />
        )}
      </div>
    </div>
  );
}
