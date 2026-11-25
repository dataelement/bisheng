import { request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import type { Plugin } from 'vite';
import { createMinioWarning } from './vite';

const objectBucket = /^\/([a-z0-9][a-z0-9.-]*)\/[^?]/;
const objectHeaders = ['range', 'if-range', 'if-match', 'if-none-match', 'if-modified-since', 'if-unmodified-since'] as const;

async function isBrowserBucketAllowed(endpoint: URL, bucket: string): Promise<boolean> {
  try {
    const response = await fetch(endpoint, {
      headers: { 'X-Object-Bucket': bucket },
      redirect: 'error',
      signal: AbortSignal.timeout(3000),
    });
    await response.body?.cancel();
    return response.status === 204;
  } catch {
    return false;
  }
}

/** Match the site's /object URL contract when a local frontend uses a newer backend. */
export function browserObjectProxy(minioTarget: string, apiTarget: string, basePath = ''): Plugin {
  return {
    name: 'bisheng:browser-object-proxy',
    apply: 'serve',
    configureServer(server) {
      const target = new URL(minioTarget);
      const requestUpstream = target.protocol === 'https:' ? httpsRequest : httpRequest;
      const bucketEndpoint = new URL('/api/v1/storage/browser-bucket', apiTarget);
      const prefixes = basePath ? [`${basePath}/object/`, '/object/'] : ['/object/'];
      const warnMinio = createMinioWarning('VITE_MINIO_PROXY_TARGET', minioTarget);

      server.middlewares.use(async (req, res, next) => {
        const requestUrl = req.url ?? '';
        const prefix = prefixes.find(candidate => requestUrl.startsWith(candidate));
        if (!prefix) return next();

        // Strip the routing prefix without re-encoding the object key or its signature.
        const objectPath = requestUrl.slice(prefix.length - 1);
        const bucket = objectBucket.exec(objectPath)?.[1];
        if ((req.method !== 'GET' && req.method !== 'HEAD') || !bucket || !await isBrowserBucketAllowed(bucketEndpoint, bucket)) {
          res.writeHead(403).end();
          return;
        }
        if (res.destroyed) return;

        const headers = Object.fromEntries(objectHeaders.map(name => [name, req.headers[name]]).filter(([, value]) => value !== undefined));
        const upstream = requestUpstream(target, { method: req.method, path: objectPath, headers: { ...headers, host: target.host } }, (response) => {
          if (response.statusCode === 403) warnMinio(requestUrl.split('?', 1)[0]);
          res.writeHead(response.statusCode ?? 502, response.headers);
          response.pipe(res);
        });
        upstream.on('error', () => {
          if (!res.headersSent) res.writeHead(502).end();
          else res.destroy();
        });
        res.on('close', () => { if (!res.writableEnded) upstream.destroy(); });
        upstream.end();
      });
    },
  };
}
