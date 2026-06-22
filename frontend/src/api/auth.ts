import { API_BASE } from "./apiBase";
import { makeApiError } from "./maps";
import type { UserOut } from "./types";

const TOKEN_KEY = "authToken";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null; // localStorage unavailable (SSR/hardened browsers)
  }
}
export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* ignore */
  }
}
export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

interface AuthResult {
  token: string;
  user: UserOut;
}

async function postAuth(path: string, body: unknown): Promise<AuthResult> {
  const res = await fetch(`${API_BASE}/auth${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `POST /auth${path} → ${res.status}`;
    try {
      const errBody = await res.json();
      if (errBody && typeof errBody.detail === "string") detail = errBody.detail;
    } catch {
      /* non-JSON body */
    }
    throw makeApiError(res.status, detail);
  }
  return (await res.json()) as AuthResult;
}

export async function login(email: string, password: string): Promise<UserOut> {
  const { token, user } = await postAuth("/login", { email, password });
  setToken(token);
  return user;
}

export async function signup(email: string, password: string, displayName: string): Promise<UserOut> {
  const { token, user } = await postAuth("/signup", {
    email,
    password,
    display_name: displayName,
  });
  setToken(token);
  return user;
}

export async function logout(): Promise<void> {
  const token = getToken();
  if (token) {
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: "POST",
        credentials: "include",
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch {
      /* best-effort; we clear locally regardless */
    }
  }
  clearToken();
}

export async function me(): Promise<UserOut | null> {
  const token = getToken();
  if (!token) return null; // no token → don't call /auth/me (it would 401)
  const res = await fetch(`${API_BASE}/auth/me`, {
    credentials: "include",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401) {
    clearToken(); // stale/expired token
    return null;
  }
  if (!res.ok) throw makeApiError(res.status, `GET /auth/me → ${res.status}`);
  return (await res.json()) as UserOut;
}
