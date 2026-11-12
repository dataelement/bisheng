import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';

export const previewRoute = '/dsh-ppt/previews';

/** Only build-listed, content-addressed template JPGs are exposed, never user files. */
export function createPreviewHandler(files, referenceRoot) {
  const root = path.resolve(referenceRoot);
  return async (req, res) => {
    const finish = (status) => {
      res.writeHead(status, { 'Cache-Control': 'no-store' });
      res.end();
    };
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      res.setHeader('Allow', 'GET, HEAD');
      finish(405);
      return;
    }
    const pathname = new URL(req.url ?? '/', 'http://localhost').pathname;
    const match = /^\/dsh-ppt\/previews\/([a-f0-9]{64})\.jpg$/.exec(pathname);
    const hash = match?.[1];
    if (!hash || !Object.hasOwn(files, hash)) return finish(404);
    const file = path.resolve(root, files[hash]);
    if (!file.startsWith(root + path.sep)) return finish(404);
    try {
      const bytes = await readFile(file);
      // A stale manifest must not serve changed bytes under an immutable URL.
      if (createHash('sha256').update(bytes).digest('hex') !== hash) return finish(404);
      const etag = '"' + hash + '"';
      const headers = {
        'Content-Type': 'image/jpeg',
        'X-Content-Type-Options': 'nosniff',
        'Cache-Control': 'public, max-age=31536000, immutable',
        ETag: etag
      };
      if (req.headers['if-none-match'] === etag) {
        res.writeHead(304, headers);
        res.end();
        return;
      }
      res.writeHead(200, { ...headers, 'Content-Length': bytes.length });
      res.end(req.method === 'HEAD' ? undefined : bytes);
    } catch {
      finish(404);
    }
  };
}

/** Optional HTTP integration keeps the PPT core usable in non-browser hosts. */
export function registerPreviewAssets(ctx, files, referenceRoot) {
  ctx.inject(['webServer'], webCtx => {
    webCtx.effect(() => webCtx.webServer.register({
      kind: 'prefix',
      path: previewRoute,
      handler: createPreviewHandler(files, referenceRoot)
    }), 'dsh-ppt: shared template previews');
  });
}
