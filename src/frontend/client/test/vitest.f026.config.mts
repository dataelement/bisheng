import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  resolve: { alias: { '~': fileURLToPath(new URL('../src', import.meta.url)) }, dedupe: ['react', 'react-dom'] },
  esbuild: { jsx: 'automatic' },
  test: { environment: 'jsdom', include: ['test/f026*.test.tsx'] },
});
