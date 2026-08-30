import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev: `npm run dev` serves on :5173 and proxies /api to the FastAPI app on
// :8000, so the frontend code always calls a same-origin `/api/...` regardless
// of mode. Build: `npm run build` emits static files into `dist/`, which the
// FastAPI app serves in prod (see src/runbook/app.py).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "dist" },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
