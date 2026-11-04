import { act, renderHook } from "@testing-library/react";
import { useClientEnvironment } from "./useClientEnvironment";
import { refreshClientEnvironment } from "~/utils/clientEnvironment";

it("keeps layout and input independent of a desktop channel", () => {
  const listeners = new Map<string, (event: { matches: boolean }) => void>();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: jest.fn((query: string) => ({
      matches: query.includes("max-width"),
      media: query,
      onchange: null,
      addEventListener: (
        _: string,
        listener: (event: { matches: boolean }) => void,
      ) => {
        listeners.set(query, listener);
      },
      removeEventListener: jest.fn(),
      addListener: jest.fn(),
      removeListener: jest.fn(),
      dispatchEvent: jest.fn(),
    })),
  });
  Object.defineProperty(navigator, "maxTouchPoints", {
    configurable: true,
    value: 5,
  });
  window.dshChatPresentation = {
    hostInfo: {
      protocolVersion: 1,
      channel: "desktop",
      deviceType: "desktop",
      os: "windows",
    },
  };
  refreshClientEnvironment();
  const { result, unmount } = renderHook(useClientEnvironment);
  expect(result.current).toMatchObject({
    channel: "desktop",
    deviceType: "desktop",
    os: "windows",
    layout: { isNarrowViewport: true },
    input: { prefersHoverInteraction: false, hasTouchInput: true },
  });
  act(() => {
    listeners.get("(max-width: 767px)")?.({ matches: false });
  });
  expect(result.current.layout.isNarrowViewport).toBe(false);
  expect(result.current.deviceType).toBe("desktop");
  act(() => {
    listeners.get("(hover: hover) and (pointer: fine)")?.({ matches: true });
  });
  expect(result.current.input.prefersHoverInteraction).toBe(true);
  expect(result.current.channel).toBe("desktop");
  unmount();
  delete window.dshChatPresentation;
});
