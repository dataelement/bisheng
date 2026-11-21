import path from 'path';
import { defineConfig, type Plugin } from 'vitest/config';
import svgr from 'vite-plugin-svgr';

const knowledgePackage = path.resolve(__dirname, '../packages/knowledge');
const uiPackage = path.resolve(__dirname, '../packages/ui');

/** Resolve workspace sources when platform/node_modules has not linked them. */
function workspacePackages(): Plugin {
  const exact: Record<string, string> = {
    '@bisheng/knowledge': path.join(knowledgePackage, 'src/index.ts'),
    '@bisheng/ui': path.join(uiPackage, 'src/index.ts'),
    '@bisheng/ui/cn': path.join(uiPackage, 'src/utils/cn.ts'),
  };
  return {
    name: 'workspace-packages',
    enforce: 'pre',
    resolveId(source) {
      return exact[source] ?? null;
    },
  };
}

export default defineConfig({
  plugins: [workspacePackages(), svgr()],
  resolve: {
    dedupe: [
      'react',
      'react-dom',
      'react-i18next',
      'lucide-react',
      'bisheng-icons',
      '@radix-ui/react-dialog',
      '@radix-ui/react-alert-dialog',
    ],
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.d.ts', 'src/test/**'],
    },
  },
});
