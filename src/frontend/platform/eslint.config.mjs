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
        { paths: [{ name: 'axios', message: 'Use @/controllers/request (wrapped module) instead of raw axios. See constitution C7.' }] },
      ],
    },
  },
  {
    // The wrapper itself legitimately imports axios.
    files: ['src/controllers/request.ts', 'src/controllers/API/index.ts'],
    rules: { 'no-restricted-imports': 'off' },
  },
)
