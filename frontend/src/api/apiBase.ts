// Single source of truth for the API base URL, shared across all api/* clients.
export const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";
