jest.mock('js-cookie', () => ({
  __esModule: true,
  default: { get: jest.fn(), remove: jest.fn() },
}));
jest.mock('./utils', () => ({
  atomWithLocalStorage: (_key: string, defaultValue: string) => defaultValue,
}));
jest.mock('~/locales/desktopLocale', () => ({ readDesktopLocale: () => null }));

describe('stored interface language initialization', () => {
  beforeEach(() => {
    jest.resetModules();
    localStorage.clear();
    Object.defineProperty(navigator, 'language', { configurable: true, value: 'en-US' });
  });

  it.each(['ja', 'zh-Hans', 'pt-BR'])('retains a JSON-encoded %s preference', async (locale) => {
    localStorage.setItem('lang', JSON.stringify(locale));
    expect((await import('./language')).default.lang).toBe(locale);
    expect(localStorage.getItem('lang')).toBe(JSON.stringify(locale));
  });

  it('retains a legacy plain language preference', async () => {
    localStorage.setItem('lang', 'ja');
    expect((await import('./language')).default.lang).toBe('ja');
  });

  it('uses the browser language when storage is unavailable', async () => {
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('Storage unavailable');
    });
    expect((await import('./language')).default.lang).toBe('en');
  });

  it('removes unsupported stored data and uses the browser language', async () => {
    localStorage.setItem('lang', JSON.stringify({ language: 'ja' }));
    expect((await import('./language')).default.lang).toBe('en');
    expect(localStorage.getItem('lang')).toBeNull();
  });
});
