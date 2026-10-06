import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development Vite serves the UI and proxies /api to the Python backend
// (uvicorn api.main:app --app-dir apps/insurance_claims, port 8000). In production the build
// in dist/ is served by FastAPI itself, so there is a single port and no CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: { outDir: "dist", emptyOutDir: true },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
    css: false,
  },
});
