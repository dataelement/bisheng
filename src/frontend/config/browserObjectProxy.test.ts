import { createServer as createHttpServer, type RequestListener } from 'node:http';
import { createServer as createViteServer } from 'vite';
import { expect, it } from 'vitest';
import { browserObjectProxy } from './browserObjectProxy';

async function listen(handler: RequestListener) {
  const server = createHttpServer(handler);
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Missing fixture address');
  return { origin: `http://127.0.0.1:${address.port}`, close: () => server.close() };
}

it('validates new object paths and forwards the unchanged signature to MinIO', async () => {
  const checked: (string | undefined)[] = [];
  const received: unknown[] = [];
  const api = await listen((request, response) => {
    expect(request.url).toBe('/api/v1/storage/browser-bucket');
    const bucket = request.headers['x-object-bucket'] as string | undefined;
    checked.push(bucket);
    response.writeHead(bucket === 'bisheng' || bucket === 'tmp-dir' ? 204 : 403).end();
  });
  const storage = await listen((request, response) => {
    received.push({
      path: request.url,
      host: request.headers.host,
      cookie: request.headers.cookie,
      authorization: request.headers.authorization,
      range: request.headers.range,
    });
    response.writeHead(200, { 'Content-Type': 'image/png' }).end('image bytes');
  });
  const vite = await createViteServer({
    configFile: false,
    appType: 'custom',
    server: { host: '127.0.0.1', port: 0, hmr: false, watch: null },
    optimizeDeps: { noDiscovery: true, include: [] },
    plugins: [browserObjectProxy(storage.origin, api.origin, '/workspace')],
  });
  try {
    await vite.listen();
    const address = vite.httpServer?.address();
    if (!address || typeof address === 'string') throw new Error('Missing frontend fixture address');
    const origin = `http://127.0.0.1:${address.port}`;
    const signedPath = '/bisheng/avatar/1/a%2Bb%20c.png?X-Amz-Signature=fixture&X-Amz-Credential=a%2Fb';

    const image = await fetch(`${origin}/workspace/object${signedPath}`, {
      headers: { cookie: 'session=fixture', authorization: 'Bearer fixture', range: 'bytes=0-10' },
    });
    expect(image.status).toBe(200);
    expect(image.headers.get('content-type')).toBe('image/png');
    expect(await image.text()).toBe('image bytes');
    expect(received).toEqual([{
      path: signedPath, host: new URL(storage.origin).host, cookie: undefined, authorization: undefined, range: 'bytes=0-10',
    }]);

    expect((await fetch(`${origin}/object/tmp-dir/file.png`, { method: 'HEAD' })).status).toBe(200);
    expect((await fetch(`${origin}/workspace/object/private/file.png`)).status).toBe(403);
    expect((await fetch(`${origin}/workspace/object/bisheng/file.png`, { method: 'POST' })).status).toBe(403);
    expect(received).toHaveLength(2);
    expect(checked).toEqual(['bisheng', 'tmp-dir', 'private']);
  } finally {
    await vite.close();
    api.close();
    storage.close();
  }
});
