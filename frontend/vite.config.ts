/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Phase 6A: minimal, standard Vite + React + TypeScript setup.
// The dev server proxy is intentionally NOT used for the API — the
// frontend always calls the backend via the full VITE_API_BASE_URL,
// so behaviour is identical in dev and in a production build.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setupTests.ts"],
    css: false,
    // A fixed, non-secret test value for VITE_API_BASE_URL so tests are
    // deterministic and independent of any local .env file.
    env: {
      VITE_API_BASE_URL: "http://localhost:8000/api/v1",
    },
  },
});
