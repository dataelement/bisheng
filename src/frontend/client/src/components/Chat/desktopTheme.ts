import { getClientEnvironment } from "~/utils/clientEnvironment";

export const DESKTOP_THEME_SESSION_KEY = "dsh:host-theme";
type HostTheme = "dark" | "light";
let lastEntry: HostTheme | undefined;
let currentTheme: HostTheme | undefined;

function hostTheme(value: unknown): HostTheme | undefined {
  return value === "dark" || value === "light" ? value : undefined;
}

/** Host appearance is tab-scoped; never write the web user's preference. */
export function readDesktopTheme(): HostTheme | undefined {
  if (
    getClientEnvironment().channel !== "desktop" ||
    typeof document === "undefined"
  )
    return undefined;
  const entry = hostTheme(
    new URLSearchParams(window.location.search).get("dshTheme"),
  );
  if (entry && entry !== lastEntry) currentTheme = entry;
  lastEntry = entry;
  currentTheme ??= hostTheme(document.documentElement.dataset.dshHostTheme);
  if (!currentTheme) {
    try {
      currentTheme = hostTheme(
        window.sessionStorage.getItem(DESKTOP_THEME_SESSION_KEY),
      );
    } catch {
      /* Use the page default. */
    }
  }
  return currentTheme;
}

export function rememberDesktopTheme(value: unknown): void {
  const theme = hostTheme(value);
  if (!theme || getClientEnvironment().channel !== "desktop") return;
  currentTheme = theme;
  document.documentElement.dataset.dshHostTheme = theme;
  try {
    const url = new URL(window.location.href);
    if (url.searchParams.has("dshTheme")) {
      url.searchParams.set("dshTheme", theme);
      window.history.replaceState(window.history.state, "", url);
    }
    lastEntry = hostTheme(url.searchParams.get("dshTheme"));
  } catch {
    /* Live memory remains authoritative if history is unavailable. */
  }
  try {
    window.sessionStorage.setItem(DESKTOP_THEME_SESSION_KEY, theme);
  } catch {
    /* Memory survives SPA routes. */
  }
}
