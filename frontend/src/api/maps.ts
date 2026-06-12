import { API_BASE } from "./apiBase";
import type { MapOut, NoteOut, Viewer } from "./types";

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} → ${res.status}`);
  return res.json() as Promise<T>;
}

export const fetchMaps = () => getJson<MapOut[]>(`${API_BASE}/maps`);
export const fetchViewers = (mapId: string) =>
  getJson<Viewer[]>(`${API_BASE}/maps/${mapId}/viewers`);
export const fetchNotes = (mapId: string, previewAs: string | null) =>
  getJson<NoteOut[]>(`${API_BASE}/maps/${mapId}/notes${previewAs ? `?preview_as=${previewAs}` : ""}`);
