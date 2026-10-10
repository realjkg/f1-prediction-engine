/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Local dev: the PWA reaches the engine same-origin — no CORS hacks.
      // The engine serves /api and /metrics on one uvicorn process (make demo).
      "/api": "http://127.0.0.1:8000",
      "/metrics": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
  },
});
