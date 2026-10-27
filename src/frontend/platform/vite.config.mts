import { diagramAssetTargets } from '../config/diagramAssets';
import { createFrontendProxy, frontendEnvDefinitions, loadFrontendEnv, resolveApiTarget } from '../config/vite';
import react from "@vitejs/plugin-react";
import fs from "fs";
import path from "path";
import { defineConfig } from "vite";
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

const apiRoutes = ["/api/", "/health"];
const fileServiceRoutes = ["/bisheng", "/tmp-dir"];

function resolveMinioProxyTarget(env: Record<string, string>): string {
  if (env.VITE_MINIO_PROXY_TARGET) {
    const configured = env.VITE_MINIO_PROXY_TARGET.trim();
    return configured.endsWith('/') ? configured : `${configured}/`;
  }

  const configCandidates = [
    path.resolve(__dirname, '../../../3.0/config.yaml'),
  ];
  for (const configPath of configCandidates) {
    try {
      if (!fs.existsSync(configPath)) continue;
      const content = fs.readFileSync(configPath, 'utf8');
      const sharepointMatch = content.match(/sharepoint:\s*["']?([^"'\n#]+)["']?/);
      const schemaMatch = content.match(/schema:\s*(true|false)/);
      if (sharepointMatch) {
        const schema = schemaMatch?.[1] === 'true' ? 'https' : 'http';
        return `${schema}://${sharepointMatch[1].trim()}/`;
      }
    } catch {
      continue;
    }
  }

  return 'http://127.0.0.1:9000/';
}

export default defineConfig(({ command, mode }) => {
  // 必须从 .env.development.local 等文件加载；仅用 process.env 时配置阶段读不到 VITE_ 变量，会回落到 7860，
  // 导致 /api/department-limit/*（仅 Gateway 提供）打到 bisheng 出现 404。
  const env = loadFrontendEnv(mode, __dirname);
  const target = resolveApiTarget(env);
  // Gateway-owned `/api/license/*` (F037/F067 status). Must not fall through to
  // FastAPI. Override with VITE_GATEWAY_PROXY_TARGET when 115 is not the lab GW.
  const gatewayTarget = env.VITE_GATEWAY_PROXY_TARGET || "http://127.0.0.1:8098";
  const fileServiceTarget = resolveMinioProxyTarget(env);
  // MinIO presigned URLs sign the Host header; this proxy's host MUST equal the
  // backend config.yaml object_storage.minio.sharepoint or every object 403s.
  if (command === 'serve') {
    console.log(
      `[bisheng:minio-proxy] dev object proxy -> ${fileServiceTarget} ` +
      `(host must equal backend sharepoint; 127.0.0.1 ≠ localhost)`,
    );
    console.log(`[bisheng:gateway-proxy] /api/license -> ${gatewayTarget}`);
  }
  const app_env_define = {
    ...app_env,
    WORKSPACE_ORIGIN: env.VITE_WORKSPACE_ORIGIN || '',
    // Origin the OnlyOffice Document Server can reach us at. It downloads the report
    // template and POSTs the save callback server-side, so `location.origin`
    // (localhost in dev) is unreachable for it — set this to your LAN IP / tunnel.
    // Empty in production: document server and app share a reachable origin.
    OFFICE_PUBLIC_ORIGIN: env.VITE_OFFICE_PUBLIC_ORIGIN || '',
  };

  const proxyLog = env.VITE_PROXY_LOG === '1';
  const rewrite = (url: string) => app_env.BASE_URL && url.startsWith(app_env.BASE_URL) ? url.slice(app_env.BASE_URL.length) : url;
  const apiProxyConfig = createFrontendProxy(target, { rewrite, verbose: proxyLog });
  const gatewayProxyConfig = createFrontendProxy(gatewayTarget, { rewrite, verbose: proxyLog });
  const fileServiceProxyConfig = createFrontendProxy(fileServiceTarget, { rewrite, verbose: proxyLog, minioEnvName: 'VITE_MINIO_PROXY_TARGET' });
  const proxyTargets: Record<string, ReturnType<typeof createFrontendProxy>> = {};
  // More specific than `/api/` and must be registered first, otherwise Vite's
  // prefix match sends `/api/license/status` to FastAPI (404 in open-source).
  proxyTargets[`${app_env.BASE_URL}/api/license`] = gatewayProxyConfig;
  apiRoutes.forEach(route => {
    proxyTargets[`${app_env.BASE_URL}${route}`] = apiProxyConfig;
  });
  fileServiceRoutes.forEach(route => {
    proxyTargets[`${app_env.BASE_URL}${route}`] = fileServiceProxyConfig;
  });

  return {
    base: app_env.BASE_URL || '/',
    // Strip all console.* / debugger from production bundles so no debug data
    // (API payloads, tokens, filenames) leaks to the browser console — same
    // policy as the client app's terser drop_console. Dev keeps them.
    esbuild: command === 'build' ? { drop: ['console', 'debugger'] } : undefined,
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
              // lowlight registers languages eagerly; keep it beside highlight.js to avoid a chunk initialization cycle.
              if (/[\\/](react-ace|ace-builds|react-syntax-highlighter|vditor|refractor|lowlight|highlight\.js|prismjs)[\\/]/.test(id)) {
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
      // Workspace viewers must use the app's initialized i18n hook instance.
      dedupe: ['react-i18next'],
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
            // `command` is vite's own signal; process.env.NODE_ENV isn't reliably
            // set during the config phase.
            aceScriptSrc: `<script src="${command === 'build' ? app_env.BASE_URL : ''}/node_modules/ace-builds/src-min-noconflict/ace.js" type="text/javascript"></script>`,
            baseUrl: app_env.BASE_URL
          }
        }
      }),
      viteStaticCopy({
        targets: [
          ...diagramAssetTargets(),
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
          },
          {
            // Full CMap set for PDFs using CID-keyed, non-embedded CJK fonts
            // (e.g. GBK-EUC-H from CEB-converted government docs). Supersedes
            // the 3 hand-picked .bcmap files in public/cmaps, which were
            // missing GBK-EUC-H and left such PDFs rendering blank.
            src: 'node_modules/pdfjs-dist/cmaps/*',
            dest: 'cmaps/'
          }
        ]
      }),
    ],
    define: {
      ...frontendEnvDefinitions(env),
      // react-draggable reads this flag on every drag/resize start in the browser.
      'process.env.DRAGGABLE_DEBUG': 'false',
      __APP_ENV__: JSON.stringify(app_env_define)
    },
    server: {
      host: '0.0.0.0',
      port: 3001,
      strictPort: true,
      proxy: {
        ...proxyTargets,
      },
    },
  };
});
