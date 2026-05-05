import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` runs the React frontend on Vite while the m3 backend lives
// on 127.0.0.1:7007 (the same port the .app's bundled server listens on).
// All /api/* calls get proxied so the dev client behaves identically to the
// .app's webview in production.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:7007",
    },
  },
});
