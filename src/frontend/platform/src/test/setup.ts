import '@testing-library/jest-dom';
import { vi } from 'vitest';

// vite injects __APP_ENV__ via define() at build time. Tests that
// transitively import modules reading __APP_ENV__ at module load (e.g.
// routes/index.tsx → userContext.tsx) need a stub before those imports
// run, so set it here in the global setup.
if (!(globalThis as any).__APP_ENV__) {
  (globalThis as any).__APP_ENV__ = { BASE_URL: '' };
}

// Radix primitives (Select, Popover, …) drive their popups with pointer capture,
// scrollIntoView and ResizeObserver, none of which jsdom implements. Stub them so
// component tests can open a bs-ui Select.
const globalScope = globalThis as { ResizeObserver?: unknown };
if (!globalScope.ResizeObserver) {
  globalScope.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = vi.fn(() => false) as never;
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
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
