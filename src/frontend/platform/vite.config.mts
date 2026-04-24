import react from "@vitejs/plugin-react-swc";
import path from "path";
import { defineConfig, loadEnv } from "vite";
import { createHtmlPlugin } from 'vite-plugin-html';
import { viteStaticCopy } from 'vite-plugin-static-copy';
import svgr from "vite-plugin-svgr";
// import { visualizer } from 'rollup-plugin-visualizer';

/**
 * 开启子路由访问
 * 开启后一般外层网管匹配【custom】时直接透传转到内层网关
 * 内层网关访问 api或者前端静态资源需要去掉【custom】前缀
 */
const app_env = { BASE_URL: '' } // /custom

const fileServiceTarget = "http://192.168.106.116:9000";

const commonProxyOptions = {
  changeOrigin: true,
  withCredentials: true,
  secure: false,
  ws: true
};

const createProxyConfig = (target: string, rewrite = true) => ({
  ...commonProxyOptions,
  target,
  ...(rewrite && {
    rewrite: (p: string) => p.replace(new RegExp(`^${app_env.BASE_URL}`), '')
  }),
  configure: (proxy: import('http-proxy').ProxyServer) => {
    proxy.on('proxyReq', (proxyReq) => {
      console.log('Proxying request to:', proxyReq.path);
    });
  }
});

const apiRoutes = ["/api/", "/health"];
const fileServiceRoutes = ["/bisheng", "/tmp-dir"];

export default defineConfig(({ mode }) => {
  // 必须从 .env.development.local 等文件加载；仅用 process.env 时配置阶段读不到 VITE_ 变量，会回落到 7860，
  // 导致 /api/department-limit/*（仅 Gateway 提供）打到 bisheng 出现 404。
  const env = loadEnv(mode, path.resolve(__dirname), "");
  const target = env.VITE_PROXY_TARGET || "http://127.0.0.1:7860";

  const apiProxyConfig = createProxyConfig(target);
  const fileServiceProxyConfig = createProxyConfig(fileServiceTarget);
  const proxyTargets: Record<string, ReturnType<typeof createProxyConfig>> = {};
  apiRoutes.forEach(route => {
    proxyTargets[`${app_env.BASE_URL}${route}`] = apiProxyConfig;
  });
  fileServiceRoutes.forEach(route => {
    proxyTargets[`${app_env.BASE_URL}${route}`] = fileServiceProxyConfig;
  });

  return {
    base: app_env.BASE_URL || '/',
    build: {
      outDir: "build",
      rollupOptions: {
        output: {
          chunkFileNames: 'assets/js/[name]-[hash].js',
          entryFileNames: 'assets/js/[name]-[hash].js',
          assetFileNames: 'assets/[ext]/[name]-[hash].[ext]',
          experimentalMinChunkSize: 10_000,
          manualChunks(id: string) {
            if (id.includes('node_modules')) {
              if (id.includes('pdfjs-dist')) {
                return 'vendor-pdf';
              }
              if (/[\\/](xlsx|mammoth|xmlbuilder|@xmldom|bluebird|lop|underscore)[\\/]/.test(id)) {
                return 'vendor-xlsx';
              }
              if (/[\\/](react-ace|ace-builds|react-syntax-highlighter|vditor|refractor|highlight\.js|prismjs)[\\/]/.test(id)) {
                return 'vendor-editor';
              }
              if (
                id.includes('mathjax') ||
                /[\\/](react-markdown|rehype-|remark-|dompurify|mdast-|hast|micromark|property-information)/.test(id)
              ) {
                return 'vendor-markdown';
              }
              return 'vendor';
            }
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
      createHtmlPlugin({
        minify: true,
        inject: {
          data: {
            aceScriptSrc: `<script src="${process.env.NODE_ENV === 'production' ? app_env.BASE_URL : ''}/node_modules/ace-builds/src-min-noconflict/ace.js" type="text/javascript"></script>`,
            baseUrl: app_env.BASE_URL
          }
        }
      }),
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
    ],
    define: {
      __APP_ENV__: JSON.stringify(app_env)
    },
    server: {
      host: '0.0.0.0',
      port: 3001,
      proxy: {
        ...proxyTargets,
      },
    },
  };
});
