import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  css: { devSourcemap: true },
  build: {
    outDir: "../static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  server: {
    // Keep workspace launch URLs stable instead of silently choosing another port.
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:8081",
      "/ready": "http://127.0.0.1:8081",
    },
  },
  test: { environment: "jsdom", include: ["src/**/*.test.{ts,tsx}"] },
});
