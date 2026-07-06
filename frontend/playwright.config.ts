import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: true,
  retries: process.env.CI ? 2 : 1, // flaky marker-count assertions retry instead of hard-failing
  workers: process.env.CI ? "50%" : undefined, // cap CI parallelism to reduce contention
  use: {
    baseURL: "http://localhost:5174",
    // maplibre needs WebGL; force software rendering so headless CI Chromium can create a GL context.
    launchOptions: { args: ["--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader"] },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev -- --port 5174",
    url: "http://localhost:5174",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    // Mirrors prod (VITE_SANDBOX=true) so the sandbox banner + tour replay pill render
    // in e2e, same as production. Existing specs opt out of the tour auto-start via
    // e2e/fixtures.ts, so the extra banner/pill is the only visible change for them.
    env: { ...process.env, VITE_SANDBOX: "true" },
  },
});
