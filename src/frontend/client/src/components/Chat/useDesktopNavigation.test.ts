import { useDesktopNavigation } from "./useDesktopNavigation";

let cleanup: (() => void) | undefined;
const mockNavigate = jest.fn();
const mockStartNewChat = jest.fn();
jest.mock('~/components/Nav/NewChat', () => ({ useStartNewChat: () => mockStartNewChat }));
let mockEmbedded = true;
jest.mock("react", () => ({
  useRef: (value: unknown) => ({ current: value }),
  useEffect: (effect: () => () => void) => {
    cleanup = effect();
  },
}));
jest.mock("react-router-dom", () => ({ useNavigate: () => mockNavigate, useLocation: () => ({ pathname: '/c/existing', search: '', key: 'initial', state: null }) }));
jest.mock("~/hooks/useClientEnvironment", () => ({
  useClientEnvironment: () => ({ channel: mockEmbedded ? "desktop" : "web" }),
}));

it("handles conversation and explicit module routes in an embedded client and removes its listener", () => {
  const listeners = new Map<string, (event: unknown) => void>();
  const prior = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      addEventListener: (name: string, listener: (event: unknown) => void) =>
        listeners.set(name, listener),
      removeEventListener: (name: string) => listeners.delete(name),
    },
  });
  try {
    useDesktopNavigation();
    const receive = listeners.get("dsh:navigate");
    for (const path of [
      "/c/new",
      "/c/cloud-a",
      "/linsight/task-a",
      "/chat/app-a/flow-a/10",
      "/knowledge",
      "/channel",
      "/apps",
      "/skills",
      "/square",
      "/menu-unavailable?plugin=knowledge_space",
    ]) {
      const preventDefault = jest.fn();
      receive?.({ detail: { path }, preventDefault });
      expect(preventDefault).toHaveBeenCalledTimes(1);
      expect(mockNavigate).toHaveBeenLastCalledWith(path);
    }
    const count = mockNavigate.mock.calls.length;
    for (const path of [
      "https://other.example",
      "/admin",
      "/c/../admin",
      "/c/a?secret=value",
      "/chat/a/b/999",
      undefined,
    ]) {
      const preventDefault = jest.fn();
      receive?.({ detail: { path }, preventDefault });
      expect(preventDefault).not.toHaveBeenCalled();
    }
    expect(mockNavigate).toHaveBeenCalledTimes(count);
    for (const path of ['/c/new', '/c/new?projectId=11111111-1111-4111-8111-111111111111']) {
      receive?.({ detail: { path, resetDraft: true }, preventDefault: jest.fn() });
      expect(mockStartNewChat).toHaveBeenLastCalledWith(path.includes('?') ? '11111111-1111-4111-8111-111111111111' : undefined);
    }
    const starts = mockStartNewChat.mock.calls.length;
    receive?.({ detail: { path: '/c/new?projectId=11111111-1111-4111-8111-111111111111', resetDraft: false }, preventDefault: jest.fn() });
    expect(mockStartNewChat).toHaveBeenCalledTimes(starts);
    expect(mockNavigate).toHaveBeenLastCalledWith('/c/new?projectId=11111111-1111-4111-8111-111111111111');
    cleanup?.();
    expect(listeners.size).toBe(0);
    mockEmbedded = false;
    useDesktopNavigation();
    expect(listeners.size).toBe(0);
  } finally {
    mockEmbedded = true;
    if (prior) Object.defineProperty(globalThis, "window", prior);
    else Reflect.deleteProperty(globalThis, "window");
  }
});
