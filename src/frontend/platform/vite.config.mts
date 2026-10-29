import { diagramAssetTargets } from '../config/diagramAssets';
import { createFrontendProxy, frontendEnvDefinitions, loadFrontendEnv, resolveApiTarget } from '../config/vite';
import react from "@vitejs/plugin-react";
import fs from "fs";
import path from "path";
import { createRequire } from "node:module";
import postcss from "postcss";
import tailwindcss from "tailwindcss";
import { defineConfig, loadEnv, type Plugin } from "vite";
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


/** Compile the public UI preset only inside this feature, preserving the legacy app theme. */
function dshContentSafetyStyles(): Plugin {
  const require = createRequire(import.meta.url);
  const scope = ".dsh-content-safety";
  const cssFile = path.resolve(__dirname, "src/style/dsh-content-safety.css");
  const tokensFile = require.resolve("@bisheng/ui/tokens.css");
  const presetFile = require.resolve("@bisheng/ui/tailwind-preset");
  const uiDirectory = path.dirname(require.resolve("@bisheng/ui"));
  const featureDirectory = path.resolve(__dirname, "src/pages/SystemPage/dsh");
  const preset = require(presetFile) as Partial<import("tailwindcss").Config>;
  const scopedSelector = (selector: string): string => {
    if (selector.startsWith(":root")) return selector.replace(":root", scope);
    // Theme owners live on html; component selectors remain inside the feature.
    const owner = selector.match(/^(\.dark(?:\.theme-green)?|\.theme-green)(?=\s|$)/);
    if (owner) return `${owner[0]} ${scope}${selector.slice(owner[0].length)}`;
    return `${scope} ${selector}`;
  };
  return {
    name: "dsh-content-safety-styles",
    enforce: "pre",
    async load(id) {
      if (id.split("?")[0] !== cssFile) return;
      this.addWatchFile(tokensFile);
      this.addWatchFile(presetFile);
      const tokens = postcss.parse(fs.readFileSync(tokensFile, "utf8"), { from: tokensFile });
      tokens.walkRules(rule => { rule.selectors = rule.selectors.map(scopedSelector); });
      const utilities = await postcss([tailwindcss({
        presets: [preset],
        content: [`${uiDirectory}/**/*.{ts,tsx}`, `${featureDirectory}/**/*.{ts,tsx}`],
        important: scope,
        corePlugins: { preflight: false },
      })]).process("@tailwind utilities;", { from: cssFile });
      const animations = new Map<string, string>();
      utilities.root.walkAtRules(/keyframes$/, rule => {
        const renamed = `dsh-safety-${rule.params}`;
        animations.set(rule.params, renamed);
        rule.params = renamed;
      });
      utilities.root.walkDecls(/^(animation|animation-name)$/, declaration => {
        declaration.value = declaration.value.replace(/[A-Za-z_][\w-]*/g,
          name => animations.get(name) ?? name);
      });
      utilities.root.walkRules(rule => {
        if (rule.parent?.type === "atrule" && /keyframes$/.test(rule.parent.name)) return;
        rule.selectors = rule.selectors.map(selector =>
          selector.includes(scope) ? selector : `${scope} ${selector}`);
      });
      // Inherit the shared system font without resetting any controls outside the feature.
      const families = preset.theme?.fontFamily;
      const fonts = typeof families === "object" ? families.sans : undefined;
      const fontFamily = Array.isArray(fonts) && fonts.every(font => typeof font === "string")
        ? fonts.join(", ") : "inherit";
      return `${tokens.toString()}\n${scope} { font-family: ${fontFamily}; }\n${utilities.root.toString()}`;
    },
    handleHotUpdate({ file, server, modules }) {
      if (file === tokensFile || file === presetFile || file.startsWith(uiDirectory + path.sep)
          || file.startsWith(featureDirectory + path.sep)) {
        const cssModule = server.moduleGraph.getModuleById(cssFile);
        if (cssModule) {
          server.moduleGraph.invalidateModule(cssModule);
          return [...modules, cssModule];
        }
      }
    },
  };
}

const commonProxyOptions = {
  changeOrigin: true,
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

const createProxyConfig = (target: string, rewrite = true, isMinio = false, verbose = false) => ({
  ...commonProxyOptions,
  target,
  ...(rewrite && {
    rewrite: (p: string) => p.replace(new RegExp(`^${app_env.BASE_URL}`), '')
  }),
  configure: (proxy: import('http-proxy').ProxyServer) => {
    // Per-request logging is opt-in (VITE_PROXY_LOG=1): on by default it prints
    // dozens of lines per page load and buries the warnings that matter.
    if (verbose) {
      proxy.on('proxyReq', (proxyReq) => {
        console.log('Proxying request to:', proxyReq.path);
      });
    }
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
  // This target must expose the app entry (nginx/gateway/app-proxy), not only
  // FastAPI. Keep the browser URL on the current origin, including WebSockets.
  proxyTargets[`${app_env.BASE_URL}/apps/`] = createFrontendProxy(
    env.VITE_APP_PROXY_TARGET || target,
    { rewrite, verbose: proxyLog },
  );
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
    // Prebundle workspace UI with its own dependency graph; the app pins a different merge version.
    optimizeDeps: { include: ["@bisheng/ui"] },
    resolve: {
      // Workspace viewers must use the app's initialized i18n hook instance.
      dedupe: ['react-i18next'],
      alias: {
        '@': path.resolve(__dirname, './src')
      }
    },
    plugins: [
      dshContentSafetyStyles(),
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
