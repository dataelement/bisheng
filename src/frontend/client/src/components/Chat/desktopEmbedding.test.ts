/** @jest-environment node */
import { isDesktopEmbedded } from './desktopEmbedding';

describe('desktop content-only presentation', () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'window');
  let search = '';
  beforeEach(() => {
    search = '';
    const values = new Map<string, string>();
    Object.defineProperty(globalThis, 'window', { configurable: true, value: {
      location: { get search() { return search; } },
      sessionStorage: { setItem: (key: string, value: string) => values.set(key, value), getItem: (key: string) => values.get(key) },
    } });
  });
  afterEach(() => {
    if (previous) Object.defineProperty(globalThis, 'window', previous);
    else Reflect.deleteProperty(globalThis, 'window');
  });
  it('preserves the explicit desktop entry across router redirects and reloads', () => {
    search = '?embed=dsh';
    expect(isDesktopEmbedded()).toBe(true);
    search = '';
    expect(isDesktopEmbedded()).toBe(true);
  });
  it('keeps standalone web navigation visible', () => {
    expect(isDesktopEmbedded()).toBe(false);
  });
});
