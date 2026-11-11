import { refreshClientEnvironment } from "~/utils/clientEnvironment";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type PropsWithChildren } from "react";
import { ThemeProvider } from "~/hooks/ThemeContext";
import { useDesktopAppearance } from "./useDesktopAppearance";

jest.mock("recoil", () => ({ useSetRecoilState: () => jest.fn() }));
jest.mock("~/store", () => ({
  __esModule: true,
  default: { fontSize: "fontSize" },
}));
jest.mock("~/utils", () => jest.requireActual("~/utils/theme"));

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  document.documentElement.className = "light";
  delete document.documentElement.dataset.dshHostTheme;
  window.matchMedia = jest.fn().mockReturnValue({
    matches: true,
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
  });
});

test("standalone Chat follows the page preference and live theme changes", async () => {
  refreshClientEnvironment();
  const view = renderHook(useDesktopAppearance);
  expect(document.body.dataset.dshChatTheme).toBe("light");
  act(() => {
    document.documentElement.className = "dark";
  });
  await waitFor(() => expect(document.body.dataset.dshChatTheme).toBe("dark"));
  act(() => {
    document.documentElement.className = "light";
  });
  await waitFor(() => expect(document.body.dataset.dshChatTheme).toBe("light"));
  view.unmount();
  expect(document.body.dataset.dshChatTheme).toBeUndefined();
});

test("embedded Chat uses the host theme for content and portalled controls", async () => {
  window.history.replaceState({}, "", "/?embed=dsh");
  document.documentElement.dataset.dshHostTheme = "dark";
  refreshClientEnvironment();
  const view = renderHook(useDesktopAppearance);
  expect(document.body.dataset.dshChatTheme).toBe("dark");
  expect(document.documentElement).toHaveClass("dark");
  act(() =>
    window.dispatchEvent(
      new CustomEvent("dsh:appearance", { detail: { theme: "light" } }),
    ),
  );
  expect(document.body.dataset.dshChatTheme).toBe("light");
  expect(document.documentElement).toHaveClass("light");
  act(() =>
    window.dispatchEvent(
      new CustomEvent("dsh:appearance", { detail: { theme: "invalid" } }),
    ),
  );
  expect(document.body.dataset.dshChatTheme).toBe("light");
  view.unmount();
});

test("retains the live theme across query removal and remount without changing web preferences", () => {
  const saved = window.localStorage.getItem("color-theme");
  window.history.replaceState({}, "", "/?embed=dsh&dshTheme=dark");
  refreshClientEnvironment();
  const first = renderHook(useDesktopAppearance);
  expect(document.body.dataset.dshChatTheme).toBe("dark");
  act(() =>
    window.dispatchEvent(
      new CustomEvent("dsh:appearance", { detail: { theme: "light" } }),
    ),
  );
  expect(new URLSearchParams(window.location.search).get("dshTheme")).toBe(
    "light",
  );
  window.history.replaceState({}, "", "/knowledge");
  first.unmount();
  delete document.documentElement.dataset.dshHostTheme;
  const next = renderHook(useDesktopAppearance);
  expect(document.body.dataset.dshChatTheme).toBe("light");
  expect(window.localStorage.getItem("color-theme")).toBe(saved);
  next.unmount();
});

test("the existing theme provider does not persist host appearance as the web preference", async () => {
  window.localStorage.setItem("color-theme", "light");
  window.history.replaceState({}, "", "/?embed=dsh&dshTheme=dark");
  refreshClientEnvironment();
  const wrapper = ({ children }: PropsWithChildren) =>
    createElement(ThemeProvider, { initialTheme: undefined, children });
  const view = renderHook(useDesktopAppearance, { wrapper });
  await waitFor(() => expect(document.documentElement).toHaveClass("dark"));
  expect(window.localStorage.getItem("color-theme")).toBe("light");
  act(() =>
    window.dispatchEvent(
      new CustomEvent("dsh:appearance", { detail: { theme: "light" } }),
    ),
  );
  expect(document.documentElement).toHaveClass("light");
  expect(window.localStorage.getItem("color-theme")).toBe("light");
  view.unmount();
});
