import "@testing-library/jest-dom/vitest";
import "./i18n";

// Node v22+ places its own localStorage getter on the global prototype.
// In jsdom (where window === globalThis), jsdom's localStorage is accessible
// via window._localStorage but Node's getter on the prototype chain shadows it.
// Override the own property so the bare `localStorage` identifier works in tests.
if (typeof window !== "undefined") {
  const jsdomStorage = (window as unknown as Record<string, unknown>)["_localStorage"];
  if (jsdomStorage !== undefined) {
    Object.defineProperty(globalThis, "localStorage", {
      value: jsdomStorage,
      writable: true,
      configurable: true,
    });
  }
}
