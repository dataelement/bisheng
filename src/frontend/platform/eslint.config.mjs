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
          'Legacy react-query v3 has been removed. Use @tanstack/react-query from the workspace catalog.',
      },
      {
        name: 'xlsx',
        message:
          'Direct xlsx imports remain frozen (ledger #7). Reuse @bisheng/file-viewers for previews; shared SheetJS versions must come from the workspace catalog.',
      },
      {
        name: 'react-color',
        message:
          'Existing react-color pickers remain frozen pending shared design-library coverage (ledger #8). Do not add new usage.',
      },
      {
        name: 'react-beautiful-dnd',
        message:
          'react-beautiful-dnd was removed (ledger #8). Use @hello-pangea/dnd from the workspace catalog for list sorting.',
      },
    ],
    patterns: [
      {
        group: ['react-beautiful-dnd/*'],
        message: 'Use @hello-pangea/dnd from the workspace catalog for list sorting.',
      },
      {
        group: ['react-query/*'],
        message:
          'Legacy react-query v3 has been removed. Use @tanstack/react-query from the workspace catalog.',
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
