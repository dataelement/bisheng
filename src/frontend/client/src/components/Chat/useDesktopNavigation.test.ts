import { useDesktopNavigation } from './useDesktopNavigation';

let cleanup: (() => void) | undefined;
const mockNavigate = jest.fn();
let mockEmbedded = true;
jest.mock('react', () => ({ useEffect: (effect: () => (() => void)) => { cleanup = effect(); } }));
jest.mock('react-router-dom', () => ({ useNavigate: () => mockNavigate }));
jest.mock('./desktopEmbedding', () => ({ isDesktopEmbedded: () => mockEmbedded }));

it('handles only conversation routes in an embedded client and removes its listener', () => {
  const listeners = new Map<string, (event: unknown) => void>();
  const prior = Object.getOwnPropertyDescriptor(globalThis, 'window');
  Object.defineProperty(globalThis, 'window', { configurable: true, value: {
    addEventListener: (name: string, listener: (event: unknown) => void) => listeners.set(name, listener),
    removeEventListener: (name: string) => listeners.delete(name),
  } });
  try {
    useDesktopNavigation();
    const receive = listeners.get('dsh:navigate');
    for (const path of ['/c/new', '/c/cloud-a', '/linsight/task-a', '/chat/app-a/flow-a/10']) {
      const preventDefault = jest.fn();
      receive?.({ detail: { path }, preventDefault });
      expect(preventDefault).toHaveBeenCalledTimes(1);
      expect(mockNavigate).toHaveBeenLastCalledWith(path);
    }
    const count = mockNavigate.mock.calls.length;
    for (const path of ['https://other.example', '/admin', '/c/../admin', '/c/a?secret=value', '/chat/a/b/999', undefined]) {
      const preventDefault = jest.fn();
      receive?.({ detail: { path }, preventDefault });
      expect(preventDefault).not.toHaveBeenCalled();
    }
    expect(mockNavigate).toHaveBeenCalledTimes(count);
    cleanup?.();
    expect(listeners.size).toBe(0);
    mockEmbedded = false;
    useDesktopNavigation();
    expect(listeners.size).toBe(0);
  } finally {
    mockEmbedded = true;
    if (prior) Object.defineProperty(globalThis, 'window', prior);
    else Reflect.deleteProperty(globalThis, 'window');
  }
});
