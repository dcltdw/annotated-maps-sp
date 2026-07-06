import { test as base } from "@playwright/test";

// Shared fixture for all EXISTING specs: seed `tourSeenV1` before the app's first
// script runs so the demo tour's auto-start (map+notes ready, logged out, unseen)
// never fires and its full-viewport click-shield can't intercept these specs'
// interactions. The new tour.spec.ts imports raw "@playwright/test" instead, so it
// keeps a clean (unseen) localStorage and the tour DOES auto-start there.
export const test = base.extend({
  page: async ({ page }, use) => {
    await page.addInitScript(() => localStorage.setItem("tourSeenV1", "1"));
    await use(page);
  },
});

export { expect } from "@playwright/test";
