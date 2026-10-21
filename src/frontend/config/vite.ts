import path from 'node:path';
import { loadEnv, type ProxyOptions } from 'vite';

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

interface FrontendProxyOptions {
  rewrite?: (url: string) => string;
  verbose?: boolean;
  minioEnvName?: string;
}

/** Shared API/WS safety; each application owns its route prefixes and service targets. */
export function createFrontendProxy(
  target: string,
  options: FrontendProxyOptions = {},
): ProxyOptions {
  const warnMinio = options.minioEnvName
    ? createMinioWarning(options.minioEnvName, target)
    : undefined;
  return {
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
}
