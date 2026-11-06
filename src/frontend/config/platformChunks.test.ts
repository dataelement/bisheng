import path from 'node:path';
import { loadConfigFromFile } from 'vite';
import { expect, it } from 'vitest';

it('keeps both lowlight versions with the highlight core they initialize', async () => {
  const loaded = await loadConfigFromFile(
    { command: 'build', mode: 'production' },
    path.resolve('platform/vite.config.mts'),
  );
  const output = loaded?.config.build?.rollupOptions?.output;
  if (!output || Array.isArray(output) || typeof output.manualChunks !== 'function') {
    throw new Error('Expected platform manual chunk function');
  }
  const context = { getModuleInfo: () => null, getModuleIds: function* () {} };
  const coreChunk = output.manualChunks('/repo/node_modules/highlight.js/lib/core.js', context);
  expect(coreChunk).toBe('vendor-editor');
  for (const id of [
    '/repo/node_modules/.pnpm/lowlight@2.9.0/node_modules/lowlight/lib/core.js',
    '/repo/node_modules/.pnpm/lowlight@1.20.0/node_modules/lowlight/lib/core.js',
    'C:\\repo\\node_modules\\lowlight\\lib\\core.js',
  ]) {
    expect(output.manualChunks(id, context)).toBe(coreChunk);
  }
});
