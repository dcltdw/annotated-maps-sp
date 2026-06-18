import { API_BASE } from "./apiBase";
import type { Group, MapOut, NoteEdit, NoteInput, NoteOut, NoteUpdateInput, Viewer } from "./types";

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

export interface ApiError extends Error { status: number; }
export function makeApiError(status: number, message: string): ApiError {
  const err = new Error(message) as ApiError;
  err.status = status;
  return err;
}

async function sendJson<T>(url: string, method: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw makeApiError(res.status, `${method} ${url} → ${res.status}`);
  return (res.status === 204 ? null : await res.json()) as T;
}

export const fetchGroups = (mapId: string) => getJson<Group[]>(`${API_BASE}/maps/${mapId}/groups`);
export const fetchNoteForEdit = (noteId: string, previewAs: string) =>
  getJson<NoteEdit>(`${API_BASE}/notes/${noteId}/edit?preview_as=${previewAs}`);
export const createNote = (mapId: string, note: NoteInput, previewAs: string) =>
  sendJson<{ id: string }>(`${API_BASE}/maps/${mapId}/notes?preview_as=${previewAs}`, "POST", note);
export const updateNote = (noteId: string, note: NoteUpdateInput, previewAs: string) =>
  sendJson<{ id: string; version: number }>(`${API_BASE}/notes/${noteId}?preview_as=${previewAs}`, "PUT", note);
export const deleteNote = (noteId: string, previewAs: string) =>
  sendJson<null>(`${API_BASE}/notes/${noteId}?preview_as=${previewAs}`, "DELETE", undefined);
