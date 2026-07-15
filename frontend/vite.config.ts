import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "Annotated Maps",
        short_name: "Maps",
        start_url: "/",
      },
    }),
  ],
  // Dev: proxy the API to the Django backend so the SPA is same-origin (no CORS).
  // Prod builds reach the API via VITE_API_BASE instead (see src/api/apiBase.ts).
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  test: { environment: "jsdom", globals: true, setupFiles: "./src/setupTests.ts", exclude: ["**/node_modules/**", "e2e/**", "e2e-prod/**", "e2e-alb/**"], environmentOptions: { jsdom: { url: "http://localhost/" } } },
});
