import { useLayoutEffect, useState } from "react";
import { getClientEnvironment } from "~/utils/clientEnvironment";

/** Window-wide portals must not change the embedded application's width breakpoints. */
function matchesContentQuery(query: string, browserMatch?: boolean): boolean {
  const widthQuery = /^\((min|max)-width:\s*(\d+(?:\.\d+)?)px\)$/.exec(query);
  if (
    widthQuery &&
    getClientEnvironment().channel === "desktop" &&
    (document.documentElement.hasAttribute("data-dsh-chat-viewport") ||
      document.documentElement.hasAttribute("data-dsh-window-dialog"))
  ) {
    const width = parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue("--dsh-chat-viewport-width"),
    );
    if (Number.isFinite(width) && width > 0) {
      const limit = Number(widthQuery[2]);
      return widthQuery[1] === "min" ? width >= limit : width <= limit;
    }
  }
  return browserMatch ?? window.matchMedia(query).matches;
}

export default function useMediaQuery(query: string) {
  const [matches, setMatches] = useState<boolean>(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    ) {
      return false;
    }
    return matchesContentQuery(query);
  });

  useLayoutEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    ) {
      return;
    }
    const media = window.matchMedia(query);
    const updateMatches = () => setMatches(matchesContentQuery(query, media.matches));
    const handleChange = (event: MediaQueryListEvent) =>
      setMatches(matchesContentQuery(query, event.matches));
    updateMatches();

    const observer = typeof MutationObserver === "function"
      ? new MutationObserver(updateMatches)
      : undefined;
    observer?.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-dsh-chat-viewport", "data-dsh-window-dialog"],
    });
    window.addEventListener("resize", updateMatches);
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", handleChange);
    } else {
      // Safari fallback
      media.addListener?.(handleChange);
    }
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", updateMatches);
      if (typeof media.removeEventListener === "function") {
        media.removeEventListener("change", handleChange);
      } else {
        media.removeListener?.(handleChange);
      }
    };
  }, [query]);

  return matches;
}
