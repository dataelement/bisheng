import { useDesktopAppearance } from './useDesktopAppearance';

let cleanup: (() => void) | undefined;
jest.mock('react', () => ({ useEffect: (effect: () => (() => void)) => { cleanup = effect(); } }));

describe('native Chat appearance handoff', () => {
  it('retains a host theme delivered before Chat mounts, updates it, and releases listeners', () => {
    const listeners = new Map<string, (event: unknown) => void>();
    const body = { dataset: {} as Record<string, string> };
    const media = { matches: true, addEventListener: jest.fn(), removeEventListener: jest.fn() };
    const host = {
      location: { search: '?embed=dsh' },
      parent: undefined as unknown,
      matchMedia: () => media,
      addEventListener: (name: string, listener: (event: unknown) => void) => listeners.set(name, listener),
      removeEventListener: (name: string) => listeners.delete(name),
    };
    host.parent = host;
    const beforeWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
    const beforeDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');
    Object.defineProperty(globalThis, 'window', { value: host, configurable: true });
    Object.defineProperty(globalThis, 'document', { value: { body, referrer: '', documentElement: { dataset: { dshHostTheme: 'light' } } }, configurable: true });
    try {
      useDesktopAppearance();
      expect(body.dataset.dshChatTheme).toBe('light');
      listeners.get('dsh:appearance')?.({ detail: { theme: 'dark' } });
      expect(body.dataset.dshChatTheme).toBe('dark');
      listeners.get('dsh:appearance')?.({ detail: { theme: 'invalid' } });
      expect(body.dataset.dshChatTheme).toBe('dark');
      cleanup?.();
      expect(listeners.size).toBe(0);
      expect(body.dataset.dshChatTheme).toBeUndefined();
    } finally {
      if (beforeWindow) Object.defineProperty(globalThis, 'window', beforeWindow);
      else Reflect.deleteProperty(globalThis, 'window');
      if (beforeDocument) Object.defineProperty(globalThis, 'document', beforeDocument);
      else Reflect.deleteProperty(globalThis, 'document');
    }
  });
});
