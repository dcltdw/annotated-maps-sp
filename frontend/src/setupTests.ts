import "@testing-library/jest-dom/vitest";
import "./i18n";

// Node v26 ships a built-in `localStorage` global that shadows jsdom's.
// Replace it with a self-contained in-memory polyfill so tests are not
// affected by jsdom internals or Node version differences.
if (typeof window !== "undefined") {
  const store: Record<string, string> = {};
  const memStorage: Storage = {
    getItem: (k) => store[k] ?? null,
    setItem: (k, v) => {
      store[k] = String(v);
    },
    removeItem: (k) => {
      delete store[k];
    },
    clear: () => {
      for (const k in store) delete store[k];
    },
    get length() {
      return Object.keys(store).length;
    },
    key: (i) => Object.keys(store)[i] ?? null,
  };
  Object.defineProperty(globalThis, "localStorage", {
    value: memStorage,
    writable: true,
    configurable: true,
  });
}
