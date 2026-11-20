import * as http from 'node:http';
import * as https from 'node:https';
import path from 'node:path';
import { loadEnv, type Plugin, type ProxyOptions } from 'vite';

/** App-local configuration wins over workspace defaults; process.env wins over files. */
export function loadFrontendEnv(
  mode: string,
  appDirectory: string,
): Record<string, string> {
  return {
    ...loadEnv(mode, path.resolve(appDirectory, '..'), ''),
    ...loadEnv(mode, appDirectory, ''),
  };
}

/** Mirror merged values into Vite's browser environment, filtering exactly its allowed prefixes. */
export function frontendEnvDefinitions(
  env: Record<string, string>,
  prefixes = ['VITE_'],
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(env)
      .filter(([key]) => prefixes.some((prefix) => key.startsWith(prefix)))
      .map(([key, value]) => [`import.meta.env.${key}`, JSON.stringify(value)]),
  );
}

export function resolveApiTarget(
  env: Record<string, string>,
  legacyKey = 'VITE_PROXY_TARGET',
): string {
  return env.VITE_API_PROXY_TARGET || env[legacyKey] || 'http://127.0.0.1:7860';
}

/** The proxy Host must equal the host used to sign MinIO URLs. Warn once per target. */
export function createMinioWarning(envName: string, target: string) {
  let warned = false;
  return (requestUrl: string) => {
    if (warned) return;
    warned = true;
    console.warn(
      `[bisheng:minio-proxy] MinIO returned 403 for "${requestUrl}". ` +
        `Set ${envName} to the backend object_storage.minio.sharepoint host ` +
        `(currently ${new URL(target).host}; localhost and 127.0.0.1 sign differently).`,
    );
  };
}

const legacyImagePath = /^\/([a-z0-9][a-z0-9.-]*)\/(?:avatar\/\d+\/[a-f0-9]{32}\.(?:jpg|png|webp|gif)|icon\/[a-f0-9]{32}\.png)\?/;
const minioSignature = /[?&]X-Amz-Signature=[a-f0-9]{64}(?:&|$)/;

/** Older dev backends sign user avatar and workbench icon URLs without the /object prefix. */
export function legacyImageProxy(minioTarget: string, basePath: string, bucket?: string): Plugin | false {
  if (!bucket) return false;

  return {
    name: 'bisheng:legacy-image-proxy',
    apply: 'serve',
    configureServer(server) {
      const target = new URL(minioTarget);
      const requestUpstream = target.protocol === 'https:' ? https.request : http.request;
      const warnMinio = createMinioWarning('VITE_MINIO_PROXY_TARGET', minioTarget);
      server.middlewares.use((req, res, next) => {
        const requestUrl = req.url ?? '';
        const objectUrl = requestUrl.startsWith(`${basePath}/`) ? requestUrl.slice(basePath.length) : '';
        if (req.method !== 'GET' || legacyImagePath.exec(objectUrl)?.[1] !== bucket || !minioSignature.test(objectUrl)) {
          next();
          return;
        }

        const headers = { ...req.headers, host: target.host };
        delete headers.cookie;
        delete headers.authorization;

        // Keep the raw object path and query so MinIO can verify the original signature.
        const proxyReq = requestUpstream(target, { method: req.method, path: objectUrl, headers }, (proxyRes) => {
          if (proxyRes.statusCode === 403) warnMinio(requestUrl.split('?', 1)[0]);
          res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
          proxyRes.pipe(res);
        });
        proxyReq.on('error', (error) => {
          if (!res.headersSent) res.writeHead(502, { 'Content-Type': 'text/plain' });
          res.end(`MinIO proxy error: ${error.message}`);
        });
        req.pipe(proxyReq);
      });
    },
  };
}

interface FrontendProxyOptions {
  rewrite?: (url: string) => string;
  verbose?: boolean;
  minioEnvName?: string;
  legacyAdminScope?: boolean;
}

/** Shared API/WS safety; each application owns its route prefixes and service targets. */
export function createFrontendProxy(
  target: string,
  options: FrontendProxyOptions = {},
): ProxyOptions {
  const warnMinio = options.minioEnvName
    ? createMinioWarning(options.minioEnvName, target)
    : undefined;
  const config: ProxyOptions = {
    target,
    changeOrigin: true,
    xfwd: true,
    secure: false,
    ws: true,
    ...(options.rewrite ? { rewrite: options.rewrite } : {}),
    configure(proxy) {
      proxy.on('proxyReqWs', (proxyReq, req) => {
        const host = req.headers.host;
        if (host) proxyReq.setHeader('x-forwarded-host', host);
      });
      if (options.verbose) {
        proxy.on('proxyReq', (proxyReq) =>
          console.log('Proxying request to:', proxyReq.path),
        );
      }
      if (warnMinio) {
        proxy.on('proxyRes', (response, req) => {
          if (response.statusCode === 403) warnMinio(req.url || '');
        });
      }
    },
  };
  if (options.legacyAdminScope) {
    config.bypass = (request) => {
      const requestUrl = request.url ?? '';
      const url = options.rewrite?.(requestUrl) ?? requestUrl;
      const isScopeRead = request.method === 'GET' && url === '/api/v1/admin/request-scope';
      const isBootstrap = request.method === 'POST' && url === '/api/v1/admin/request-scope/bootstrap';
      if (!isScopeRead && !isBootstrap) return;
      if (request.headers['transfer-encoding'] || Number(request.headers['content-length'] ?? 0) !== 0) return;
      // The old endpoint authenticates the current admin and returns their actual scope.
      request.method = 'GET';
      request.url = '/api/v1/admin/tenant-scope';
    };
  }
  return config;
}
