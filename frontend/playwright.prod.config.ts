import { defineConfig, devices } from "@playwright/test";

// Runs the production-bundle guards against `vite preview` (the built, concatenated
// CSS/JS), separate from the dev-server e2e suite (which relies on dev-only features
// like window.__map and a different CSS injection order).
export default defineConfig({
  testDir: "./e2e-prod",
  timeout: 60_000,
  retries: process.env.CI ? 2 : 1,
  use: {
    baseURL: "http://localhost:4174",
    serviceWorkers: "block", // keep the PWA SW out of the way of route mocks
    // maplibre needs WebGL; force software rendering so headless CI Chromium gets a GL context.
    launchOptions: {
      args: ["--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader"],
    },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run build && npm run preview -- --port 4174 --strictPort",
    url: "http://localhost:4174",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000, // build + preview startup
  },
});
