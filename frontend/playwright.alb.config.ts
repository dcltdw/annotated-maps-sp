import { defineConfig, devices } from "@playwright/test";

// Smoke config for a LIVE deployment (the pipeline's ALB URL, or any
// deployed instance). No webServer: BASE_URL must point at a running app.
//   BASE_URL=http://<alb-host> npm run e2e:alb
export default defineConfig({
  testDir: "./e2e-alb",
  timeout: 60_000, // remote target: generous first-load budget (cold caches)
  retries: 1,
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:5174",
    screenshot: "on", // evidence artifacts, green or red
    // maplibre needs WebGL; software rendering for headless CI Chromium.
    launchOptions: { args: ["--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader"] },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
