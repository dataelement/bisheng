// Development-only component harness. No production routes or API behavior change.
import { createServer } from 'vite';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const directory = path.dirname(fileURLToPath(import.meta.url));
const client = path.resolve(directory, '../..');
const fixture = path.join(directory, 'preview.tsx');
const server = await createServer({
  configFile: false,
  root: client,
  cacheDir: '/tmp/bisheng-knowledge-preview-vite-cache',
  optimizeDeps: { entries: ['test/knowledge-home-preview/index.html'] },
  plugins: [{
    name: 'knowledge-home-isolated-fixtures',
    enforce: 'pre',
    resolveId(source, importer) {
      if (importer?.includes('/pages/knowledge/') && (
        ['~/hooks', '~/Providers', '~/api/knowledge', '~/api/request'].includes(source)
        || /\/hooks\/use(KnowledgeSpaceLists|KnowledgeSpacePermissions|SpaceActions)$/.test(source)
      )) return fixture;
      if (source.startsWith('~/') || source.startsWith('@/')) return this.resolve(path.resolve(client, 'src', source.slice(2)), importer, { skipSelf: true });
      return null;
    },
  }],
  esbuild: { jsx: 'automatic' },
  server: { host: '127.0.0.1', port: 4175, strictPort: true },
});
await server.listen();
process.stdout.write('Isolated component preview: http://127.0.0.1:4175/test/knowledge-home-preview/\n');
