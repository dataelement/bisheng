// ESLint 9 flat config — @bisheng/ui shared package.
// This package is new code: NO suppressions file, zero tolerance from day one.
import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**', 'doc_build/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    languageOptions: {
      globals: { ...globals.browser, ...globals.es2021 },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-hooks/exhaustive-deps': 'error',
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/ban-ts-comment': ['error', { 'ts-expect-error': 'allow-with-description' }],
      'no-console': ['error', { allow: ['warn', 'error'] }],
      // Package contract: presentation-only — no HTTP at all.
      'no-restricted-imports': ['error', { paths: [{ name: 'axios', message: '@bisheng/ui is presentation-only; no HTTP allowed (package contract).' }] }],
    },
  },
  {
    // Node CJS tooling (token build, tailwind preset, docs scripts) — not component source.
    files: ['**/*.cjs'],
    languageOptions: { globals: { ...globals.node } },
    rules: {
      '@typescript-eslint/no-require-imports': 'off',
      'no-console': 'off',
    },
  },
)
