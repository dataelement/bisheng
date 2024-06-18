import react from "@vitejs/plugin-react-swc";
import { visualizer } from "rollup-plugin-visualizer";
import { defineConfig } from "vite";
import { viteStaticCopy } from 'vite-plugin-static-copy';
import svgr from "vite-plugin-svgr";
const apiRoutes = ["^/api/", "^/gw/", "/health"];
import path from "path";
// Use environment variable to determine the target.
const target = process.env.VITE_PROXY_TARGET || "http://192.168.106.120:3002";
// const target = process.env.VITE_PROXY_TARGET || "http://192.168.106.115:8098";
// const target = process.env.VITE_PROXY_TARGET || "http://192.168.106.116:7861";
// const target = process.env.VITE_PROXY_TARGET || "http://192.168.2.7:7860";

const proxyTargets = apiRoutes.reduce((proxyObj, route) => {

  proxyObj['/gw/api/v1/group'] = {
    target: target,
    changeOrigin: true,
    withCredentials: true,
    rewrite: (path) => path.replace(/^\/gw\/api\/v1\/group/, '/group'),
    secure: false,
    ws: true,
  };
  proxyObj[route] = {
    target: target,
    changeOrigin: true,
    withCredentials: true,
    secure: false,
    ws: true,
  };
  // 文件服务地址
  proxyObj['/bisheng'] = {
    target: "http://127.0.0.1:50061",
    changeOrigin: true,
    withCredentials: true,
    secure: false
  }
  return proxyObj;
}, {});

export default defineConfig(() => {
  return {
    // base: '/poo',
    build: {
      // minify: 'esbuild', // 使用 esbuild 进行 Tree Shaking 和压缩
      outDir: "build",
      rollupOptions: {
        output: {
          manualChunks: {
            acebuilds: ['react-ace', 'ace-builds', 'react-syntax-highlighter', 'rehype-mathjax', 'react-markdown'],
            reactflow: ['reactflow'],
            pdfjs: ['pdfjs-dist'],
            reactdrop: ['react-window', 'react-beautiful-dnd', 'react-dropzone']
          }
        }
      }
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src')
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
          },
          {
            src: 'node_modules/pdfjs-dist/build/pdf.worker.min.js',
            dest: './'
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
