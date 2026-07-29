// ESLint 9 flat config — @bisheng/file-viewers shared package.
// New code: NO suppressions file, zero tolerance from day one.
// xlsx/xlsx-populate are allowed here on purpose: this package is the single
// consolidation point for Excel parsing (ledger #7) — apps must not import them.
import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**'] },
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
      // Presentation + parsing only — no HTTP client, no state managers.
      'no-restricted-imports': ['error', { paths: [{ name: 'axios', message: '@bisheng/file-viewers takes URLs via props and uses fetch; no HTTP client deps.' }] }],
      // Copy must come from the shared i18n namespace, never be hardcoded.
      'no-restricted-syntax': [
        'error',
        { selector: 'Literal[value=/[\\u4e00-\\u9fff]/]', message: 'Hardcoded Chinese — use the shared: i18n namespace (packages/locales src/shared).' },
        { selector: 'TemplateElement[value.raw=/[\\u4e00-\\u9fff]/]', message: 'Hardcoded Chinese — use the shared: i18n namespace (packages/locales src/shared).' },
        { selector: 'JSXText[value=/[\\u4e00-\\u9fff]/]', message: 'Hardcoded Chinese — use the shared: i18n namespace (packages/locales src/shared).' },
      ],
    },
  },
)
