import { frontendConfig } from '../config/eslint.mjs';

export default frontendConfig({
  ignores: [
    'dist/**',
    'build/**',
    'node_modules/**',
    'public/**',
    'coverage/**',
    'doc_build/**',
    // Docs-site widgets: rspress content, not app code. The docs site has no
    // i18n (rspress.config.ts) so its copy is Chinese by design.
    'docs-site/**',
    'scripts/**',
    '*.config.{js,ts,mjs,mts}',
    'tailwind.config.js',
    'postcss.config.js',
  ],
  restrictedImports: {
    paths: [
      {
        name: 'axios',
        message:
          'Use ~/api/request (wrapped module) instead of raw axios. See constitution C7.',
      },
      // Deprecated libs frozen at current usage (ledger #5, #8):
      // existing violations live in eslint-suppressions.json, new imports are blocked.
      {
        name: 'recoil',
        message:
          'Recoil is archived by Meta and frozen — no new atoms/selectors/imports (ledger #5). Server state goes to @tanstack/react-query; new client-global state awaits the Jotai migration decision.',
      },
      {
        name: 'react-beautiful-dnd',
        message:
          'react-beautiful-dnd is deprecated upstream (no React 18 StrictMode support) and frozen; use @hello-pangea/dnd when migrating (ledger #8).',
      },
      {
        name: 'react-virtualized',
        message:
          'react-virtualized is frozen — the app standardizes on react-window / @tanstack/react-virtual (ledger #8). Do not add new usage.',
      },
    ],
    patterns: [
      {
        group: ['recoil/*'],
        message:
          'Recoil is archived by Meta and frozen (ledger #5). Do not add new usage.',
      },
    ],
  },
  requestFiles: ['src/api/request.ts'],
  localizeHint: 'useLocalize → localize()',
});
