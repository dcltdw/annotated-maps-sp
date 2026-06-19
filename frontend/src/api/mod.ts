import { API_BASE } from "./apiBase";

export interface ModItem {
  id: string;
  kind: string;
  title: string;
  snippet: string;
  author_name: string;
  session_key: string;
  created_ip: string | null;
  created_at: string;
  updated_at: string;
  version: number;
  map_name: string;
}

export interface ModDeleteBody {
  ids?: string[];
  session_key?: string;
  created_ip?: string;
}

async function modFetch<T>(path: string, token: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      "X-Mod-Token": token,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export const modRecent = (token: string, limit = 50) =>
  modFetch<ModItem[]>(`/mod/recent?limit=${limit}`, token);
export const modDelete = (token: string, body: ModDeleteBody) =>
  modFetch<{ deleted: number }>(`/mod/delete`, token, "POST", body);
