import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The React source lives in frontend/ and builds into static/, which server.py serves.
// In dev (`npm run dev`), /api is proxied to a locally running `python server.py`.
export default defineConfig({
  root: "frontend",
  plugins: [react()],
  build: { outDir: "../static", emptyOutDir: true },
  server: { proxy: { "/api": "http://localhost:8000" } },
});
