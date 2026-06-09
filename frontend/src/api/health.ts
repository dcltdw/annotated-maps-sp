const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

export async function fetchHealth(): Promise<{ status: string; version: string }> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}
