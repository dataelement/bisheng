import { frontendConfig } from '../config/eslint.mjs';

export default frontendConfig({
  ignores: [
    'dist/**',
    'build/**',
    'node_modules/**',
    'public/**',
    'local-packages/**',
    'coverage/**',
    '*.config.{js,ts,mjs,mts}',
    'vite.config.mts',
  ],
  restrictedImports: {
    paths: [
      {
        name: 'axios',
        message:
          'Use @/controllers/request (wrapped module) instead of raw axios. See constitution C7.',
      },
      // Deprecated/vulnerable libs frozen at current usage (ledger #6-#8):
      // existing violations live in eslint-suppressions.json, new imports are blocked.
      {
        name: 'react-query',
        message:
          'react-query v3 is unmaintained and frozen; migration to @tanstack/react-query is pending (ledger #6). Do not add new usage.',
      },
      {
        name: 'xlsx',
        message:
          'xlsx has known vulnerabilities (prototype pollution / ReDoS) and is frozen pending replacement (ledger #7). Do not add new usage.',
      },
      {
        name: 'react-color',
        message:
          'react-color is deprecated and frozen (ledger #8). Do not add new usage.',
      },
      {
        name: 'react-beautiful-dnd',
        message:
          'react-beautiful-dnd is deprecated upstream (no React 18 StrictMode support) and frozen; use @hello-pangea/dnd when migrating (ledger #8).',
      },
    ],
    patterns: [
      {
        group: ['react-query/*'],
        message:
          'react-query v3 is unmaintained and frozen (ledger #6). Do not add new usage.',
      },
      {
        group: ['xlsx-populate', 'xlsx-populate/*'],
        message:
          'xlsx-populate is frozen pending Excel-lib consolidation (ledger #7). Do not add new usage.',
      },
    ],
  },
  requestFiles: ['src/controllers/request.ts', 'src/controllers/API/index.ts'],
  localizeHint: 'useTranslation → t()',
});
