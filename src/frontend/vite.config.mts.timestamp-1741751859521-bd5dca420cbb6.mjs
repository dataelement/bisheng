// vite.config.mts
import react from "file:///Users/shanghang/dataelem/bisheng/src/frontend/node_modules/@vitejs/plugin-react-swc/index.mjs";
import path from "path";
import { defineConfig } from "file:///Users/shanghang/dataelem/bisheng/src/frontend/node_modules/vite/dist/node/index.js";
import { createHtmlPlugin } from "file:///Users/shanghang/dataelem/bisheng/src/frontend/node_modules/vite-plugin-html/dist/index.mjs";
import { viteStaticCopy } from "file:///Users/shanghang/dataelem/bisheng/src/frontend/node_modules/vite-plugin-static-copy/dist/index.js";
import svgr from "file:///Users/shanghang/dataelem/bisheng/src/frontend/node_modules/vite-plugin-svgr/dist/index.js";
var __vite_injected_original_dirname = "/Users/shanghang/dataelem/bisheng/src/frontend";
var target = process.env.VITE_PROXY_TARGET || "http://192.168.106.120:3003";
var apiRoutes = ["^/api/", "/health"];
var proxyTargets = apiRoutes.reduce((proxyObj, route) => {
  proxyObj[route] = {
    target,
    changeOrigin: true,
    withCredentials: true,
    secure: false,
    ws: true
  };
  return proxyObj;
}, {});
proxyTargets["/bisheng"] = {
  target: "http://192.168.106.116:9000",
  changeOrigin: true,
  withCredentials: true,
  secure: false
};
proxyTargets["/tmp-dir"] = proxyTargets["/bisheng"];
proxyTargets["/custom_base/api"] = {
  target,
  changeOrigin: true,
  withCredentials: true,
  secure: false,
  rewrite: (path2) => {
    return path2.replace(/^\/custom_base\/api/, "/api");
  },
  configure: (proxy, options) => {
    proxy.on("proxyReq", (proxyReq, req, res) => {
      console.log("Proxying request to:", proxyReq.path);
    });
  }
};
var app_env = { BASE_URL: "" };
var vite_config_default = defineConfig(() => {
  return {
    base: app_env.BASE_URL || "/",
    build: {
      // minify: 'esbuild', // 使用 esbuild 进行 Tree Shaking 和压缩
      outDir: "build",
      rollupOptions: {
        output: {
          manualChunks: {
            acebuilds: ["react-ace", "ace-builds", "react-syntax-highlighter", "rehype-mathjax", "react-markdown"],
            reactflow: ["@xyflow/react"],
            pdfjs: ["pdfjs-dist"],
            reactdrop: ["react-window", "react-beautiful-dnd", "react-dropzone"]
          }
        }
      }
    },
    resolve: {
      alias: {
        "@": path.resolve(__vite_injected_original_dirname, "./src")
      }
    },
    plugins: [
      react(),
      svgr(),
      createHtmlPlugin({
        minify: true,
        inject: {
          data: {
            // include: [/index\.html$/],
            aceScriptSrc: `<script src="${process.env.NODE_ENV === "production" ? app_env.BASE_URL : ""}/node_modules/ace-builds/src-min-noconflict/ace.js" type="text/javascript"></script>`,
            baseUrl: app_env.BASE_URL
          }
        }
      }),
      viteStaticCopy({
        targets: [
          {
            src: [
              "node_modules/ace-builds/src-min-noconflict/ace.js",
              "node_modules/ace-builds/src-min-noconflict/mode-json.js",
              "node_modules/ace-builds/src-min-noconflict/worker-json.js",
              "node_modules/ace-builds/src-min-noconflict/mode-yaml.js",
              "node_modules/ace-builds/src-min-noconflict/worker-yaml.js"
            ],
            dest: "node_modules/ace-builds/src-min-noconflict/"
          },
          {
            src: "node_modules/pdfjs-dist/build/pdf.worker.min.js",
            dest: "./"
          }
        ]
      })
      // 打包物体积报告
      // visualizer({
      //   open: true,
      // })
    ],
    define: {
      __APP_ENV__: JSON.stringify(app_env)
    },
    server: {
      host: "0.0.0.0",
      port: 3001,
      proxy: {
        ...proxyTargets
      }
    }
  };
});
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcubXRzIl0sCiAgInNvdXJjZXNDb250ZW50IjogWyJjb25zdCBfX3ZpdGVfaW5qZWN0ZWRfb3JpZ2luYWxfZGlybmFtZSA9IFwiL1VzZXJzL3NoYW5naGFuZy9kYXRhZWxlbS9iaXNoZW5nL3NyYy9mcm9udGVuZFwiO2NvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9maWxlbmFtZSA9IFwiL1VzZXJzL3NoYW5naGFuZy9kYXRhZWxlbS9iaXNoZW5nL3NyYy9mcm9udGVuZC92aXRlLmNvbmZpZy5tdHNcIjtjb25zdCBfX3ZpdGVfaW5qZWN0ZWRfb3JpZ2luYWxfaW1wb3J0X21ldGFfdXJsID0gXCJmaWxlOi8vL1VzZXJzL3NoYW5naGFuZy9kYXRhZWxlbS9iaXNoZW5nL3NyYy9mcm9udGVuZC92aXRlLmNvbmZpZy5tdHNcIjtpbXBvcnQgcmVhY3QgZnJvbSBcIkB2aXRlanMvcGx1Z2luLXJlYWN0LXN3Y1wiO1xuaW1wb3J0IHBhdGggZnJvbSBcInBhdGhcIjtcbmltcG9ydCB7IGRlZmluZUNvbmZpZyB9IGZyb20gXCJ2aXRlXCI7XG5pbXBvcnQgeyBjcmVhdGVIdG1sUGx1Z2luIH0gZnJvbSAndml0ZS1wbHVnaW4taHRtbCc7XG5pbXBvcnQgeyB2aXRlU3RhdGljQ29weSB9IGZyb20gJ3ZpdGUtcGx1Z2luLXN0YXRpYy1jb3B5JztcbmltcG9ydCBzdmdyIGZyb20gXCJ2aXRlLXBsdWdpbi1zdmdyXCI7XG4vLyBpbXBvcnQgeyB2aXN1YWxpemVyIH0gZnJvbSAncm9sbHVwLXBsdWdpbi12aXN1YWxpemVyJztcblxuLy8gVXNlIGVudmlyb25tZW50IHZhcmlhYmxlIHRvIGRldGVybWluZSB0aGUgdGFyZ2V0LlxuLy8gIGNvbnN0IHRhcmdldCA9IHByb2Nlc3MuZW52LlZJVEVfUFJPWFlfVEFSR0VUIHx8IFwiaHR0cDovLzEyNy4wLjAuMTo3ODYwXCI7XG4gY29uc3QgdGFyZ2V0ID0gcHJvY2Vzcy5lbnYuVklURV9QUk9YWV9UQVJHRVQgfHwgXCJodHRwOi8vMTkyLjE2OC4xMDYuMTIwOjMwMDNcIjtcbmNvbnN0IGFwaVJvdXRlcyA9IFtcIl4vYXBpL1wiLCBcIi9oZWFsdGhcIl07XG5cbmNvbnN0IHByb3h5VGFyZ2V0cyA9IGFwaVJvdXRlcy5yZWR1Y2UoKHByb3h5T2JqLCByb3V0ZSkgPT4ge1xuICBwcm94eU9ialtyb3V0ZV0gPSB7XG4gICAgdGFyZ2V0OiB0YXJnZXQsXG4gICAgY2hhbmdlT3JpZ2luOiB0cnVlLFxuICAgIHdpdGhDcmVkZW50aWFsczogdHJ1ZSxcbiAgICBzZWN1cmU6IGZhbHNlLFxuICAgIHdzOiB0cnVlXG4gIH07XG4gIHJldHVybiBwcm94eU9iajtcbn0sIHt9KTtcbi8vIFx1NjU4N1x1NEVGNlx1NjcwRFx1NTJBMVx1NTczMFx1NTc0MFxucHJveHlUYXJnZXRzWycvYmlzaGVuZyddID0ge1xuICB0YXJnZXQ6IFwiaHR0cDovLzE5Mi4xNjguMTA2LjExNjo5MDAwXCIsXG4gIGNoYW5nZU9yaWdpbjogdHJ1ZSxcbiAgd2l0aENyZWRlbnRpYWxzOiB0cnVlLFxuICBzZWN1cmU6IGZhbHNlXG59XG5wcm94eVRhcmdldHNbJy90bXAtZGlyJ10gPSBwcm94eVRhcmdldHNbJy9iaXNoZW5nJ11cbnByb3h5VGFyZ2V0c1snL2N1c3RvbV9iYXNlL2FwaSddID0ge1xuICB0YXJnZXQsXG4gIGNoYW5nZU9yaWdpbjogdHJ1ZSxcbiAgd2l0aENyZWRlbnRpYWxzOiB0cnVlLFxuICBzZWN1cmU6IGZhbHNlLFxuICByZXdyaXRlOiAocGF0aCkgPT4ge1xuICAgIHJldHVybiBwYXRoLnJlcGxhY2UoL15cXC9jdXN0b21fYmFzZVxcL2FwaS8sICcvYXBpJyk7XG4gIH0sXG4gIGNvbmZpZ3VyZTogKHByb3h5LCBvcHRpb25zKSA9PiB7XG4gICAgcHJveHkub24oJ3Byb3h5UmVxJywgKHByb3h5UmVxLCByZXEsIHJlcykgPT4ge1xuICAgICAgY29uc29sZS5sb2coJ1Byb3h5aW5nIHJlcXVlc3QgdG86JywgcHJveHlSZXEucGF0aCk7XG4gICAgfSk7XG4gIH1cbn1cblxuLyoqXG4gKiBcdTVGMDBcdTU0MkZcdTVCNTBcdThERUZcdTc1MzFcdThCQkZcdTk1RUVcbiAqIFx1NUYwMFx1NTQyRlx1NTQwRVx1NEUwMFx1ODIyQ1x1NTkxNlx1NUM0Mlx1N0Y1MVx1N0JBMVx1NTMzOVx1OTE0RFx1MzAxMGN1c3RvbVx1MzAxMVx1NjVGNlx1NzZGNFx1NjNBNVx1OTAwRlx1NEYyMFx1OEY2Q1x1NTIzMFx1NTE4NVx1NUM0Mlx1N0Y1MVx1NTE3M1xuICogXHU1MTg1XHU1QzQyXHU3RjUxXHU1MTczXHU4QkJGXHU5NUVFIGFwaVx1NjIxNlx1ODAwNVx1NTI0RFx1N0FFRlx1OTc1OVx1NjAwMVx1OEQ0NFx1NkU5MFx1OTcwMFx1ODk4MVx1NTNCQlx1NjM4OVx1MzAxMGN1c3RvbVx1MzAxMVx1NTI0RFx1N0YwMFxuKi9cbmNvbnN0IGFwcF9lbnYgPSB7IEJBU0VfVVJMOiAnJyB9XG4vLyBjb25zdCBhcHBfZW52ID0geyBCQVNFX1VSTDogJy9wbGF0Zm9ybScgfVxuXG5leHBvcnQgZGVmYXVsdCBkZWZpbmVDb25maWcoKCkgPT4ge1xuICByZXR1cm4ge1xuICAgIGJhc2U6IGFwcF9lbnYuQkFTRV9VUkwgfHwgJy8nLFxuICAgIGJ1aWxkOiB7XG4gICAgICAvLyBtaW5pZnk6ICdlc2J1aWxkJywgLy8gXHU0RjdGXHU3NTI4IGVzYnVpbGQgXHU4RkRCXHU4ODRDIFRyZWUgU2hha2luZyBcdTU0OENcdTUzOEJcdTdGMjlcbiAgICAgIG91dERpcjogXCJidWlsZFwiLFxuICAgICAgcm9sbHVwT3B0aW9uczoge1xuICAgICAgICBvdXRwdXQ6IHtcbiAgICAgICAgICBtYW51YWxDaHVua3M6IHtcbiAgICAgICAgICAgIGFjZWJ1aWxkczogWydyZWFjdC1hY2UnLCAnYWNlLWJ1aWxkcycsICdyZWFjdC1zeW50YXgtaGlnaGxpZ2h0ZXInLCAncmVoeXBlLW1hdGhqYXgnLCAncmVhY3QtbWFya2Rvd24nXSxcbiAgICAgICAgICAgIHJlYWN0ZmxvdzogWydAeHlmbG93L3JlYWN0J10sXG4gICAgICAgICAgICBwZGZqczogWydwZGZqcy1kaXN0J10sXG4gICAgICAgICAgICByZWFjdGRyb3A6IFsncmVhY3Qtd2luZG93JywgJ3JlYWN0LWJlYXV0aWZ1bC1kbmQnLCAncmVhY3QtZHJvcHpvbmUnXVxuICAgICAgICAgIH1cbiAgICAgICAgfVxuICAgICAgfVxuICAgIH0sXG4gICAgcmVzb2x2ZToge1xuICAgICAgYWxpYXM6IHtcbiAgICAgICAgJ0AnOiBwYXRoLnJlc29sdmUoX19kaXJuYW1lLCAnLi9zcmMnKVxuICAgICAgfVxuICAgIH0sXG4gICAgcGx1Z2luczogW1xuICAgICAgcmVhY3QoKSxcbiAgICAgIHN2Z3IoKSxcbiAgICAgIGNyZWF0ZUh0bWxQbHVnaW4oe1xuICAgICAgICBtaW5pZnk6IHRydWUsXG4gICAgICAgIGluamVjdDoge1xuICAgICAgICAgIGRhdGE6IHtcbiAgICAgICAgICAgIC8vIGluY2x1ZGU6IFsvaW5kZXhcXC5odG1sJC9dLFxuICAgICAgICAgICAgYWNlU2NyaXB0U3JjOiBgPHNjcmlwdCBzcmM9XCIke3Byb2Nlc3MuZW52Lk5PREVfRU5WID09PSAncHJvZHVjdGlvbicgPyBhcHBfZW52LkJBU0VfVVJMIDogJyd9L25vZGVfbW9kdWxlcy9hY2UtYnVpbGRzL3NyYy1taW4tbm9jb25mbGljdC9hY2UuanNcIiB0eXBlPVwidGV4dC9qYXZhc2NyaXB0XCI+PC9zY3JpcHQ+YCxcbiAgICAgICAgICAgIGJhc2VVcmw6IGFwcF9lbnYuQkFTRV9VUkxcbiAgICAgICAgICB9XG4gICAgICAgIH1cbiAgICAgIH0pLFxuICAgICAgdml0ZVN0YXRpY0NvcHkoe1xuICAgICAgICB0YXJnZXRzOiBbXG4gICAgICAgICAge1xuICAgICAgICAgICAgc3JjOiBbXG4gICAgICAgICAgICAgICdub2RlX21vZHVsZXMvYWNlLWJ1aWxkcy9zcmMtbWluLW5vY29uZmxpY3QvYWNlLmpzJyxcbiAgICAgICAgICAgICAgJ25vZGVfbW9kdWxlcy9hY2UtYnVpbGRzL3NyYy1taW4tbm9jb25mbGljdC9tb2RlLWpzb24uanMnLFxuICAgICAgICAgICAgICAnbm9kZV9tb2R1bGVzL2FjZS1idWlsZHMvc3JjLW1pbi1ub2NvbmZsaWN0L3dvcmtlci1qc29uLmpzJyxcbiAgICAgICAgICAgICAgJ25vZGVfbW9kdWxlcy9hY2UtYnVpbGRzL3NyYy1taW4tbm9jb25mbGljdC9tb2RlLXlhbWwuanMnLFxuICAgICAgICAgICAgICAnbm9kZV9tb2R1bGVzL2FjZS1idWlsZHMvc3JjLW1pbi1ub2NvbmZsaWN0L3dvcmtlci15YW1sLmpzJ1xuICAgICAgICAgICAgXSxcbiAgICAgICAgICAgIGRlc3Q6ICdub2RlX21vZHVsZXMvYWNlLWJ1aWxkcy9zcmMtbWluLW5vY29uZmxpY3QvJ1xuICAgICAgICAgIH0sXG4gICAgICAgICAge1xuICAgICAgICAgICAgc3JjOiAnbm9kZV9tb2R1bGVzL3BkZmpzLWRpc3QvYnVpbGQvcGRmLndvcmtlci5taW4uanMnLFxuICAgICAgICAgICAgZGVzdDogJy4vJ1xuICAgICAgICAgIH1cbiAgICAgICAgXVxuICAgICAgfSksXG4gICAgICAvLyBcdTYyNTNcdTUzMDVcdTcyNjlcdTRGNTNcdTc5RUZcdTYyQTVcdTU0NEFcbiAgICAgIC8vIHZpc3VhbGl6ZXIoe1xuICAgICAgLy8gICBvcGVuOiB0cnVlLFxuICAgICAgLy8gfSlcbiAgICBdLFxuICAgIGRlZmluZToge1xuICAgICAgX19BUFBfRU5WX186IEpTT04uc3RyaW5naWZ5KGFwcF9lbnYpXG4gICAgfSxcbiAgICBzZXJ2ZXI6IHtcbiAgICAgIGhvc3Q6ICcwLjAuMC4wJyxcbiAgICAgIHBvcnQ6IDMwMDEsXG4gICAgICBwcm94eToge1xuICAgICAgICAuLi5wcm94eVRhcmdldHMsXG4gICAgICB9LFxuICAgIH0sXG4gIH07XG59KTtcbiJdLAogICJtYXBwaW5ncyI6ICI7QUFBOFQsT0FBTyxXQUFXO0FBQ2hWLE9BQU8sVUFBVTtBQUNqQixTQUFTLG9CQUFvQjtBQUM3QixT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
