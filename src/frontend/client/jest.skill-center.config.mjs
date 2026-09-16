// Node-only file and persistence tests; the application Jest setup needs a DOM.
import config from './jest.config.cjs';
export default {
  ...config,
  testEnvironment: 'node',
  setupFilesAfterEnv: [],
  collectCoverage: false,
  testMatch: ['**/components/Skills/__tests__/*.test.ts'],
};
