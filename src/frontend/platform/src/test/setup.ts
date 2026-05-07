import '@testing-library/jest-dom';
import { vi } from 'vitest';

// vite injects __APP_ENV__ via define() at build time. Tests that
// transitively import modules reading __APP_ENV__ at module load (e.g.
// routes/index.tsx → userContext.tsx) need a stub before those imports
// run, so set it here in the global setup.
if (!(globalThis as any).__APP_ENV__) {
  (globalThis as any).__APP_ENV__ = { BASE_URL: '' };
}

// Mock react-i18next (matching client/test/setupTests.js pattern)
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: 'en' },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: vi.fn() },
}));
