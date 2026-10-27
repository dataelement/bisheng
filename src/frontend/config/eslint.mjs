import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';

/** Shared quality policy; legacy suppressions and frozen dependencies stay app-local. */
export function frontendConfig({
  ignores,
  restrictedImports,
  requestFiles,
  localizeHint,
}) {
  return tseslint.config(
    { ignores },
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
        '@typescript-eslint/ban-ts-comment': [
          'error',
          { 'ts-expect-error': 'allow-with-description' },
        ],
        'no-console': ['error', { allow: ['warn', 'error'] }],
        'no-restricted-imports': ['error', restrictedImports],
        'no-restricted-syntax': [
          'error',
          {
            selector: 'Literal[value=/[\\u4e00-\\u9fff]/]',
            message: `Hardcoded Chinese string — route copy through i18n (${localizeHint}). Ledger #28.`,
          },
          {
            selector: 'TemplateElement[value.raw=/[\\u4e00-\\u9fff]/]',
            message: `Hardcoded Chinese in template string — route copy through i18n (${localizeHint}). Ledger #28.`,
          },
          {
            selector: 'JSXText[value=/[\\u4e00-\\u9fff]/]',
            message: `Hardcoded Chinese JSX text — route copy through i18n (${localizeHint}). Ledger #28.`,
          },
        ],
      },
    },
    { files: requestFiles, rules: { 'no-restricted-imports': 'off' } },
  );
}
