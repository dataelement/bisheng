import { act, renderHook } from "@testing-library/react";
import { refreshClientEnvironment } from "~/utils/clientEnvironment";
import usePrefersMobileLayout from "./usePrefersMobileLayout";

it("keeps the desktop layout across resizes and route changes after a DSH entry", () => {
  let width = 595;
  const originalMatchMedia = window.matchMedia;
  window.matchMedia = (query) => ({
    media: query,
    get matches() {
      return query === "(max-width: 767px)" && width <= 767;
    },
    onchange: null,
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    addListener: jest.fn(),
    removeListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
  const resize = (nextWidth: number) => act(() => {
    width = nextWidth;
    window.dispatchEvent(new Event("resize"));
  });
  const navigate = (path: string) => act(() => {
    window.history.replaceState({}, "", path);
    refreshClientEnvironment();
  });

  const { result, unmount } = renderHook(usePrefersMobileLayout);
  try {
    expect(result.current).toBe(true);
    resize(768);
    expect(result.current).toBe(false);
    resize(767);
    expect(result.current).toBe(true);
    navigate("/workspace/knowledge?embed=mobile-app");
    expect(result.current).toBe(true);

    navigate("/workspace/knowledge?embed=dsh");
    expect(result.current).toBe(false);
    navigate("/workspace/channel");
    resize(1200);
    expect(result.current).toBe(false);
    resize(390);
    expect(result.current).toBe(false);
  } finally {
    unmount();
    window.matchMedia = originalMatchMedia;
    window.history.replaceState({}, "", "/");
    window.sessionStorage.clear();
  }
});
