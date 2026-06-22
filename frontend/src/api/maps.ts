import { API_BASE } from "./apiBase";
import { getToken } from "./auth";
import type { AppendInput, AppendUpdateInput, Group, MapOut, NoteEdit, NoteInput, NoteOut, NoteUpdateInput, Viewer } from "./types";

function authHeaders(base: Record<string, string> = {}): Record<string, string> {
  const token = getToken();
  return token ? { ...base, Authorization: `Bearer ${token}` } : base;
}
function previewQuery(previewAs: string | null): string {
  return previewAs ? `?preview_as=${previewAs}` : "";
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { credentials: "include", headers: authHeaders() });
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
    credentials: "include",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${method} ${url} → ${res.status}`;
    try {
      const errBody = await res.json();
      if (errBody && typeof errBody.detail === "string") detail = errBody.detail;
    } catch {
      /* non-JSON error body */
    }
    throw makeApiError(res.status, detail);
  }
  return (res.status === 204 ? null : await res.json()) as T;
}

export const fetchGroups = (mapId: string) => getJson<Group[]>(`${API_BASE}/maps/${mapId}/groups`);
export const fetchNoteForEdit = (noteId: string, previewAs: string | null) =>
  getJson<NoteEdit>(`${API_BASE}/notes/${noteId}/edit${previewQuery(previewAs)}`);
export const createNote = (mapId: string, note: NoteInput, previewAs: string | null) =>
  sendJson<{ id: string }>(`${API_BASE}/maps/${mapId}/notes${previewQuery(previewAs)}`, "POST", note);
export const updateNote = (noteId: string, note: NoteUpdateInput, previewAs: string | null) =>
  sendJson<{ id: string; version: number }>(`${API_BASE}/notes/${noteId}${previewQuery(previewAs)}`, "PUT", note);
export const deleteNote = (noteId: string, previewAs: string | null) =>
  sendJson<null>(`${API_BASE}/notes/${noteId}${previewQuery(previewAs)}`, "DELETE", undefined);
export const createAppend = (parentId: string, append: AppendInput, previewAs: string | null) =>
  sendJson<{ id: string }>(`${API_BASE}/notes/${parentId}/appends${previewQuery(previewAs)}`, "POST", append);
export const updateAppend = (appendId: string, append: AppendUpdateInput, previewAs: string | null) =>
  sendJson<{ id: string; version: number }>(`${API_BASE}/appends/${appendId}${previewQuery(previewAs)}`, "PUT", append);
