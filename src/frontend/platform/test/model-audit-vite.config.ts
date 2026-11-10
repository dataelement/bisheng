// Isolated preview only; avoid the production HTML plugin injecting the full app login.
import react from "@vitejs/plugin-react-swc";
import path from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  root: path.resolve(__dirname, ".."),
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "../src") } },
  define: { __APP_ENV__: JSON.stringify({ BASE_URL: "" }) },
  server: {
    host: "127.0.0.1",
    port: 3302,
    strictPort: true,
    proxy: { "/api/": { target: "http://127.0.0.1:8786", changeOrigin: true } },
  },
});
