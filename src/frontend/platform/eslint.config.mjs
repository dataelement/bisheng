// ESLint 9 flat config — quality gate for the platform app.
// Policy: legacy violations are frozen in eslint-suppressions.json (may only shrink);
// new code must be clean. Run `npm run lint` locally, CI enforces on every PR.
import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'

export default tseslint.config(
  {
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
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    languageOptions: {
      globals: { ...globals.browser, ...globals.es2021, ...globals.node },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // All gate rules are "error" so they are frozen via suppressions and block new code.
      'react-hooks/exhaustive-deps': 'error',
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/ban-ts-comment': ['error', { 'ts-expect-error': 'allow-with-description' }],
      'no-console': ['error', { allow: ['warn', 'error'] }],
      // C7: HTTP must go through the wrapped request module.
      'no-restricted-imports': [
        'error',
        {
          paths: [
            { name: 'axios', message: 'Use @/controllers/request (wrapped module) instead of raw axios. See constitution C7.' },
            // Deprecated/vulnerable libs frozen at current usage (ledger #6-#8):
            // existing violations live in eslint-suppressions.json, new imports are blocked.
            { name: 'react-query', message: 'react-query v3 is unmaintained and frozen; migration to @tanstack/react-query is pending (ledger #6). Do not add new usage.' },
            { name: 'xlsx', message: 'xlsx has known vulnerabilities (prototype pollution / ReDoS) and is frozen pending replacement (ledger #7). Do not add new usage.' },
            { name: 'react-color', message: 'react-color is deprecated and frozen (ledger #8). Do not add new usage.' },
            { name: 'react-beautiful-dnd', message: 'react-beautiful-dnd is deprecated upstream (no React 18 StrictMode support) and frozen; use @hello-pangea/dnd when migrating (ledger #8).' },
          ],
          patterns: [
            { group: ['react-query/*'], message: 'react-query v3 is unmaintained and frozen (ledger #6). Do not add new usage.' },
            { group: ['xlsx-populate', 'xlsx-populate/*'], message: 'xlsx-populate is frozen pending Excel-lib consolidation (ledger #7). Do not add new usage.' },
          ],
        },
      ],
    },
  },
  {
    // The wrapper itself legitimately imports axios.
    files: ['src/controllers/request.ts', 'src/controllers/API/index.ts'],
    rules: { 'no-restricted-imports': 'off' },
  },
)
