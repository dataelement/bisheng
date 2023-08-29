import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import svgr from "vite-plugin-svgr";
const apiRoutes = ["^/api/v1/", "/health"];

// Use environment variable to determine the target.
const target = process.env.VITE_PROXY_TARGET || "http://192.168.106.120:7860";
// const target = process.env.VITE_PROXY_TARGET || "http://192.168.106.116:7860";

const proxyTargets = apiRoutes.reduce((proxyObj, route) => {
  proxyObj[route] = {
    target: target,
    changeOrigin: true,
    secure: false,
    ws: true,
  };
  return proxyObj;
}, {});

export default defineConfig(() => {
  return {
    build: {
      outDir: "build",
    },
    plugins: [react(), svgr()],
    server: {
      host: '0.0.0.0',
      port: 3001,
      proxy: {
        ...proxyTargets,
      },
    },
  };
});
