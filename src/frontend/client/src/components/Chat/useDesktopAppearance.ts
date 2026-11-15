import { useEffect } from "react";
import { useClientEnvironment } from "~/hooks/useClientEnvironment";
import { readDesktopTheme, rememberDesktopTheme } from "./desktopTheme";

/** Appearance-only bridge. The parent receives readiness, never credentials or files. */
export function useDesktopAppearance() {
  const { channel } = useClientEnvironment();
  useEffect(() => {
    const media =
      typeof window.matchMedia === "function"
        ? window.matchMedia("(prefers-color-scheme: dark)")
        : undefined;
    let parentOrigin = "";
    try {
      parentOrigin = new URL(document.referrer).origin;
    } catch {
      /* Standalone page. */
    }
    const embedded = window.parent !== window && !!parentOrigin;
    const nativeEmbedded = channel === "desktop";
    let hostTheme = readDesktopTheme();
    const apply = () => {
      const root = document.documentElement;
      const pageTheme = root.classList.contains("dark")
        ? "dark"
        : root.classList.contains("light")
          ? "light"
          : media?.matches
            ? "dark"
            : "light";
      const theme = hostTheme || pageTheme;
      document.body.dataset.dshChatTheme = theme;
      if (nativeEmbedded && hostTheme) {
        rememberDesktopTheme(hostTheme);
        if (!root.classList.contains(theme)) {
          root.classList.remove(theme === "dark" ? "light" : "dark");
          root.classList.add(theme);
        }
      }
    };
    const receive = (event: MessageEvent) => {
      if (
        !embedded ||
        event.source !== window.parent ||
        event.origin !== parentOrigin
      )
        return;
      if (
        event.data?.type === "dsh:appearance" &&
        ["dark", "light"].includes(event.data.theme)
      ) {
        hostTheme = event.data.theme;
        apply();
      }
    };
    const receiveNative = (event: Event) => {
      const theme = (event as CustomEvent<{ theme?: unknown }>).detail?.theme;
      if (nativeEmbedded && (theme === "dark" || theme === "light")) {
        hostTheme = theme;
        apply();
      }
    };
    const observer = new MutationObserver(apply);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    apply();
    window.addEventListener("dsh:appearance", receiveNative);
    window.addEventListener("message", receive);
    if (typeof media?.addEventListener === "function")
      media.addEventListener("change", apply);
    else media?.addListener?.(apply);
    if (embedded)
      window.parent.postMessage({ type: "bisheng:ready" }, parentOrigin);
    return () => {
      observer.disconnect();
      delete document.body.dataset.dshChatTheme;
      window.removeEventListener("dsh:appearance", receiveNative);
      window.removeEventListener("message", receive);
      if (typeof media?.removeEventListener === "function")
        media.removeEventListener("change", apply);
      else media?.removeListener?.(apply);
    };
  }, [channel]);
}
