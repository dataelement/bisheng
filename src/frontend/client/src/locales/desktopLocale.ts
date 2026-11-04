import { isDesktopEmbedded } from '~/components/Chat/desktopEmbedding';

const SESSION_KEY = 'dsh:host-locale';

export function isNativeDesktop(): boolean {
  return isDesktopEmbedded() && typeof window.dshChatPresentation?.reportLanding === 'function';
}

function hostLocale(value: unknown): 'zh' | 'en' | undefined {
  return value === 'zh' || value === 'en' ? value : undefined;
}

/** Presentation state stays in this tab; the web language cookie and localStorage are untouched. */
export function readDesktopLocale(): 'zh-Hans' | 'en' | undefined {
  if (!isNativeDesktop()) return undefined;
  const root = document.documentElement;
  let locale = hostLocale(root.dataset.dshHostLocale)
    ?? hostLocale(new URLSearchParams(window.location.search).get('dshLocale'));
  if (!locale) {
    try { locale = hostLocale(window.sessionStorage.getItem(SESSION_KEY)); }
    catch { /* A blocked sessionStorage must not prevent host language delivery. */ }
  }
  return locale === 'zh' ? 'zh-Hans' : locale;
}

export function rememberDesktopLocale(value: unknown): void {
  const locale = hostLocale(value);
  if (!isNativeDesktop() || !locale) return;
  document.documentElement.dataset.dshHostLocale = locale;
  document.documentElement.lang = locale === 'zh' ? 'zh-Hans' : 'en';
  // Keep a hard reload from replaying the entry URL's old locale after a live switch.
  const url = new URL(window.location.href);
  if (url.searchParams.has('dshLocale') && url.searchParams.get('dshLocale') !== locale) {
    url.searchParams.set('dshLocale', locale);
    window.history.replaceState(window.history.state, '', url);
  }
  try { window.sessionStorage.setItem(SESSION_KEY, locale); }
  catch { /* The in-memory document value remains sufficient until the next reload. */ }
}

/** One listener per shell, with an explicit disposer for route teardown and hot reload. */
export function subscribeDesktopLocale(listener: () => void): () => void {
  if (!isNativeDesktop()) return () => {};
  const receive = (event: Event) => {
    const detail: unknown = (event as CustomEvent<unknown>).detail;
    if (!detail || typeof detail !== 'object' || !('locale' in detail) || !hostLocale(detail.locale)) return;
    rememberDesktopLocale(detail.locale);
    listener();
  };
  window.addEventListener('dsh:locale', receive);
  return () => window.removeEventListener('dsh:locale', receive);
}
