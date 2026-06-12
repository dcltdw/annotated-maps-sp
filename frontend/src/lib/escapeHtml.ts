const ENTITIES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

// Single-pass replace: each metacharacter maps directly to its entity, so the
// "&" rule never re-encodes the "&" inside an entity it just emitted.
export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (ch) => ENTITIES[ch]);
}
