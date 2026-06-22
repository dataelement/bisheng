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

const commonProxyOptions = {
  changeOrigin: true,
  withCredentials: true,
  secure: false,
  ws: true
};

// Emit one loud, actionable warning the first time MinIO answers a proxied
// object request with 403. For presigned (SigV4) URLs to the public bucket a
// 403 is almost always SignatureDoesNotMatch: changeOrigin rewrites Host to the
// proxy target host, but the URL was signed for the backend `sharepoint` host.
// The classic trap is `127.0.0.1` vs `localhost` (not interchangeable for
// signing). Without this, the only symptom is silently broken images.
let warnedMinio403 = false;
const warnMinioSignatureMismatch = (targetHost: string, requestUrl: string) => {
  if (warnedMinio403) return;
  warnedMinio403 = true;
  console.warn(
    `\n\x1b[33m[bisheng:minio-proxy] ⚠️  MinIO returned 403 for "${requestUrl}".\n` +
    `  Almost certainly a SigV4 host mismatch: the dev proxy forwards Host=${targetHost},\n` +
    `  but the presigned URL was signed for a different host.\n` +
    `  Fix: set VITE_MINIO_PROXY_TARGET so its host EXACTLY equals backend config.yaml\n` +
    `  object_storage.minio.sharepoint  (note: 127.0.0.1 ≠ localhost).\x1b[0m\n`,
  );
};

const createProxyConfig = (target: string, rewrite = true, isMinio = false) => ({
  ...commonProxyOptions,
  target,
  ...(rewrite && {
    rewrite: (p: string) => p.replace(new RegExp(`^${app_env.BASE_URL}`), '')
  }),
  configure: (proxy: import('http-proxy').ProxyServer) => {
    proxy.on('proxyReq', (proxyReq) => {
      console.log('Proxying request to:', proxyReq.path);
    });
    if (isMinio) {
      const targetHost = new URL(target).host;
      proxy.on('proxyRes', (proxyRes, req) => {
        if (proxyRes.statusCode === 403) {
          warnMinioSignatureMismatch(targetHost, req.url || '');
        }
      });
    }
  }
});

const apiRoutes = ["/api/", "/health"];
const fileServiceRoutes = ["/bisheng", "/tmp-dir"];

export default defineConfig(({ command, mode }) => {
  // 必须从 .env.development.local 等文件加载；仅用 process.env 时配置阶段读不到 VITE_ 变量，会回落到 7860，
  // 导致 /api/department-limit/*（仅 Gateway 提供）打到 bisheng 出现 404。
  const env = loadEnv(mode, path.resolve(__dirname), "");
  const target = env.VITE_PROXY_TARGET || "http://127.0.0.1:7860";
  const fileServiceTarget = env.VITE_MINIO_PROXY_TARGET || "http://127.0.0.1:9100";
  // MinIO presigned URLs sign the Host header; this proxy's host MUST equal the
  // backend config.yaml object_storage.minio.sharepoint or every object 403s.
  if (command === 'serve') {
    console.log(
      `[bisheng:minio-proxy] dev object proxy -> ${fileServiceTarget} ` +
      `(host must equal backend sharepoint; 127.0.0.1 ≠ localhost)`,
    );
  }
  const app_env_define = {
    ...app_env,
    WORKSPACE_ORIGIN: env.VITE_WORKSPACE_ORIGIN || '',
  };

  const apiProxyConfig = createProxyConfig(target);
  const fileServiceProxyConfig = createProxyConfig(fileServiceTarget, true, true);
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
      __APP_ENV__: JSON.stringify(app_env_define)
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
