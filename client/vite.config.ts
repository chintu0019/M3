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
      "/api": {
        target: "http://127.0.0.1:7007",
        // SSE streams (e.g. /api/v1/chat) need headers/body flushed line-by-
        // line. The default http-proxy config buffers, so the chat rail sees
        // no tool_call/tool_result/final events until the request closes —
        // which can be 30+ seconds for slow CLIs. selfHandleResponse=false
        // and ws=true together keep streams unbuffered.
        changeOrigin: true,
        ws: true,
        selfHandleResponse: false,
      },
    },
  },
});
