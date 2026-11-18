import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    languageOptions: { globals: { ...globals.browser, ...globals.es2021 } },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-hooks/exhaustive-deps': 'error',
      '@typescript-eslint/no-explicit-any': 'error',
      'no-restricted-imports': ['error', { paths: [
        { name: 'axios', message: 'Knowledge interactions receive host-owned API services.' },
        { name: 'recoil', message: 'Shared knowledge interactions use local React state.' },
        { name: 'zustand', message: 'Shared knowledge interactions use local React state.' },
      ] }],
    },
  },
);
