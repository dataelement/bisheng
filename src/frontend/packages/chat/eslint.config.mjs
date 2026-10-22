import sharedUiRules from '../ui/eslint.config.mjs';
export default [
  ...sharedUiRules,
  { files: ['src/**/*.{ts,tsx}'], rules: {
    'no-restricted-imports': ['error', {
      paths: ['axios', 'recoil', 'zustand', 'react-query', '@tanstack/react-query', 'react-router-dom'],
      patterns: ['~/*', '@/*', '**/client/src/**', '**/platform/src/**'],
    }],
  } },
];
