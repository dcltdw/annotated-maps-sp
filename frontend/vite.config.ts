/// <reference types="vitest/config" />
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
  test: { environment: "jsdom", globals: true, setupFiles: "./src/setupTests.ts" },
});
