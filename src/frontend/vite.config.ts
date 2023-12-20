import react from "@vitejs/plugin-react-swc";
import { visualizer } from "rollup-plugin-visualizer";
import { defineConfig } from "vite";
import { viteStaticCopy } from 'vite-plugin-static-copy';
import svgr from "vite-plugin-svgr";
const apiRoutes = ["^/api/", "/health"];

// Use environment variable to determine the target.
// const target = process.env.VITE_PROXY_TARGET || "http://192.168.106.116:7861";
 const target = process.env.VITE_PROXY_TARGET || "http://127.0.0.1:7860";

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
      rollupOptions: {
        output: {
          manualChunks: {
            acebuilds: ['ace-builds', 'react-syntax-highlighter', 'rehype-mathjax'],
            pdfjs: ['pdfjs-dist']
          }
        }
      }
    },
    plugins: [
      react(),
      svgr(),
      viteStaticCopy({
        targets: [
          {
            src: [
              'node_modules/ace-builds/src-min-noconflict/ace.js',
              'node_modules/ace-builds/src-min-noconflict/mode-json.js',
              'node_modules/ace-builds/src-min-noconflict/worker-json.js',
              'node_modules/ace-builds/src-min-noconflict/mode-yaml.js',
              'node_modules/ace-builds/src-min-noconflict/worker-yaml.js'
            ],
            dest: 'node_modules/ace-builds/src-min-noconflict/'
          }
        ]
      }),
      // 打包物体积报告
      // visualizer({
      //   open: true,
      // })
    ],
    server: {
      host: '0.0.0.0',
      port: 3001,
      proxy: {
        ...proxyTargets,
      },
    },
  };
});
