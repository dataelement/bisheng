import { act, renderHook, waitFor } from "@testing-library/react";
import useMediaQuery from "./useMediaQuery";

let mockChannel = "desktop";
jest.mock("~/utils/clientEnvironment", () => ({
  getClientEnvironment: () => ({ channel: mockChannel }),
}));

const originalMatchMedia = window.matchMedia;
let viewportWidth = 1130;
let hover = true;

beforeEach(() => {
  mockChannel = "desktop";
  viewportWidth = 1130;
  hover = true;
  document.documentElement.removeAttribute("data-dsh-chat-viewport");
  document.documentElement.removeAttribute("data-dsh-window-dialog");
  document.documentElement.style.removeProperty("--dsh-chat-viewport-width");
  window.matchMedia = jest.fn((query: string) => ({
    get matches() {
      const width = /^\((min|max)-width:\s*(\d+)px\)$/.exec(query);
      return width
        ? width[1] === "min" ? viewportWidth >= Number(width[2]) : viewportWidth <= Number(width[2])
        : hover;
    },
    media: query,
    onchange: null,
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    addListener: jest.fn(),
    removeListener: jest.fn(),
    dispatchEvent: jest.fn(),
  })) as typeof window.matchMedia;
});

afterEach(() => {
  window.matchMedia = originalMatchMedia;
  document.documentElement.removeAttribute("data-dsh-chat-viewport");
  document.documentElement.removeAttribute("data-dsh-window-dialog");
  document.documentElement.style.removeProperty("--dsh-chat-viewport-width");
});

function pinContentWidth(width: string) {
  document.documentElement.style.setProperty("--dsh-chat-viewport-width", width);
  document.documentElement.setAttribute("data-dsh-window-dialog", "open");
}

it("keeps narrow content in its layout when the native modal expands the window", async () => {
  viewportWidth = 700;
  const { result } = renderHook(() => useMediaQuery("(max-width: 767px)"));
  expect(result.current).toBe(true);
  act(() => {
    pinContentWidth("700px");
    viewportWidth = 940;
    window.dispatchEvent(new Event("resize"));
  });
  await waitFor(() => expect(result.current).toBe(true));
  act(() => {
    viewportWidth = 700;
    document.documentElement.removeAttribute("data-dsh-window-dialog");
    window.dispatchEvent(new Event("resize"));
  });
  await waitFor(() => expect(result.current).toBe(true));
});

it("uses a prepared content seat before the native window starts expanding", () => {
  document.documentElement.style.setProperty("--dsh-chat-viewport-width", "700px");
  document.documentElement.setAttribute("data-dsh-chat-viewport", "ready");
  const { result } = renderHook(() => useMediaQuery("(max-width: 767px)"));
  expect(result.current).toBe(true);
  act(() => {
    viewportWidth = 940;
    window.dispatchEvent(new Event("resize"));
  });
  expect(result.current).toBe(true);
});

it("updates when the prepared seat is installed or released", async () => {
  const { result } = renderHook(() => useMediaQuery("(max-width: 767px)"));
  expect(result.current).toBe(false);
  act(() => {
    document.documentElement.style.setProperty("--dsh-chat-viewport-width", "700px");
    document.documentElement.setAttribute("data-dsh-chat-viewport", "ready");
  });
  await waitFor(() => expect(result.current).toBe(true));
  act(() => document.documentElement.removeAttribute("data-dsh-chat-viewport"));
  await waitFor(() => expect(result.current).toBe(false));
});

it.each([
  ["(min-width: 1024px)", false],
  ["(max-width: 1023px)", true],
])("uses the reserved desktop width for %s", (query, expected) => {
  pinContentWidth("890px");
  const { result } = renderHook(() => useMediaQuery(query as string));
  expect(result.current).toBe(expected);
});

it("updates after the host changes its reserved width while a modal stays open", async () => {
  pinContentWidth("700px");
  const { result } = renderHook(() => useMediaQuery("(max-width: 767px)"));
  act(() => pinContentWidth("890px"));
  await waitFor(() => expect(result.current).toBe(false));
});

it("leaves pointer capability queries attached to the browser", () => {
  pinContentWidth("700px");
  const { result } = renderHook(() => useMediaQuery("(hover: hover) and (pointer: fine)"));
  expect(result.current).toBe(true);
  act(() => {
    hover = false;
    window.dispatchEvent(new Event("resize"));
  });
  expect(result.current).toBe(false);
});

it.each(["", "invalid"])("falls back to the browser if the reserved width is %s", (width) => {
  pinContentWidth(width);
  const { result } = renderHook(() => useMediaQuery("(max-width: 767px)"));
  expect(result.current).toBe(false);
});

it("ignores desktop presentation styles in an ordinary browser", () => {
  mockChannel = "web";
  pinContentWidth("700px");
  const { result } = renderHook(() => useMediaQuery("(max-width: 767px)"));
  expect(result.current).toBe(false);
});
