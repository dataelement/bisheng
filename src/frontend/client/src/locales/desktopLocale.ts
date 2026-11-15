import type { i18n as I18n } from "i18next";
import {
  getClientEnvironment,
  readDesktopPresentation,
} from "~/utils/clientEnvironment";

const SESSION_KEY = "dsh:host-locale";
let lastEntry: "zh" | "en" | undefined;

export function isNativeDesktop(): boolean {
  try {
    return (
      getClientEnvironment().channel === "desktop" &&
      typeof readDesktopPresentation().reportLanding === "function"
    );
  } catch {
    return false;
  }
}

function hostLocale(value: unknown): "zh" | "en" | undefined {
  return value === "zh" || value === "en" ? value : undefined;
}

/** Presentation state stays in this tab; the web language cookie and localStorage are untouched. */
export function readDesktopLocale(): "zh-Hans" | "en" | undefined {
  if (!isNativeDesktop()) return undefined;
  const root = document.documentElement;
  const entry = hostLocale(
    new URLSearchParams(window.location.search).get("dshLocale"),
  );
  const localeFromEntry = entry && entry !== lastEntry ? entry : undefined;
  lastEntry = entry;
  let locale =
    localeFromEntry ?? hostLocale(root.dataset.dshHostLocale) ?? entry;
  if (!locale) {
    try {
      locale = hostLocale(window.sessionStorage.getItem(SESSION_KEY));
    } catch {
      /* A blocked sessionStorage must not prevent host language delivery. */
    }
  }
  return locale === "zh" ? "zh-Hans" : locale;
}

export function rememberDesktopLocale(value: unknown): void {
  const locale = hostLocale(value);
  if (!isNativeDesktop() || !locale) return;
  document.documentElement.dataset.dshHostLocale = locale;
  document.documentElement.lang = locale === "zh" ? "zh-Hans" : "en";
  // Keep a hard reload from replaying the entry URL's old locale after a live switch.
  try {
    const url = new URL(window.location.href);
    if (
      url.searchParams.has("dshLocale") &&
      url.searchParams.get("dshLocale") !== locale
    ) {
      url.searchParams.set("dshLocale", locale);
      window.history.replaceState(window.history.state, "", url);
    }
    lastEntry = hostLocale(url.searchParams.get("dshLocale"));
  } catch {
    /* The document value survives unavailable history. */
  }
  try {
    window.sessionStorage.setItem(SESSION_KEY, locale);
  } catch {
    /* The in-memory document value remains sufficient until the next reload. */
  }
}

/** One listener per shell, with an explicit disposer for route teardown and hot reload. */
export function subscribeDesktopLocale(listener: () => void): () => void {
  if (!isNativeDesktop()) return () => {};
  const receive = (event: Event) => {
    const detail: unknown = (event as CustomEvent<unknown>).detail;
    if (
      !detail ||
      typeof detail !== "object" ||
      !("locale" in detail) ||
      !hostLocale(detail.locale)
    )
      return;
    rememberDesktopLocale(detail.locale);
    listener();
  };
  window.addEventListener("dsh:locale", receive);
  return () => window.removeEventListener("dsh:locale", receive);
}

/** A Web document may enter the host through an SPA route after i18n initialized. */
export function changeInterfaceLanguage(i18n: I18n, language: string) {
  if (isNativeDesktop()) {
    const detector = i18n.services
      .languageDetector as typeof i18n.services.languageDetector & {
      options?: { caches?: string[] };
    };
    if (detector?.options) detector.options.caches = [];
  }
  return i18n.changeLanguage(language);
}
