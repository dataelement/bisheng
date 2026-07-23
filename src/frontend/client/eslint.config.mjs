// ESLint 9 flat config — quality gate for the client app.
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
      'coverage/**',
      'doc_build/**',
      'scripts/**',
      '*.config.{js,ts,mjs,mts}',
      'tailwind.config.js',
      'postcss.config.js',
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
            { name: 'axios', message: 'Use ~/api/request (wrapped module) instead of raw axios. See constitution C7.' },
            // Deprecated libs frozen at current usage (ledger #5, #8):
            // existing violations live in eslint-suppressions.json, new imports are blocked.
            { name: 'recoil', message: 'Recoil is archived by Meta and frozen — no new atoms/selectors/imports (ledger #5). Server state goes to @tanstack/react-query; new client-global state awaits the Jotai migration decision.' },
            { name: 'react-beautiful-dnd', message: 'react-beautiful-dnd is deprecated upstream (no React 18 StrictMode support) and frozen; use @hello-pangea/dnd when migrating (ledger #8).' },
            { name: 'react-virtualized', message: 'react-virtualized is frozen — the app standardizes on react-window / @tanstack/react-virtual (ledger #8). Do not add new usage.' },
          ],
          patterns: [
            { group: ['recoil/*'], message: 'Recoil is archived by Meta and frozen (ledger #5). Do not add new usage.' },
          ],
        },
      ],
    },
  },
  {
    // The wrapper itself legitimately imports axios.
    files: ['src/api/request.ts'],
    rules: { 'no-restricted-imports': 'off' },
  },
)
