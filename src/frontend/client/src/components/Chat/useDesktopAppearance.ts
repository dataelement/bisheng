import { useEffect } from 'react';
import { isDesktopEmbedded } from './desktopEmbedding';

/** Appearance-only bridge. The parent receives readiness, never credentials or files. */
export function useDesktopAppearance() {
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    let parentOrigin = '';
    try { parentOrigin = new URL(document.referrer).origin; } catch { /* Standalone page. */ }
    const embedded = window.parent !== window && !!parentOrigin;
    const nativeEmbedded = isDesktopEmbedded();
    const initialTheme = document.documentElement.dataset.dshHostTheme;
    let hostTheme: 'dark' | 'light' | undefined = nativeEmbedded && (initialTheme === 'dark' || initialTheme === 'light') ? initialTheme : undefined;
    const apply = () => {
      const root = document.documentElement;
      const pageTheme = root.classList.contains('dark') ? 'dark' : root.classList.contains('light') ? 'light' : media.matches ? 'dark' : 'light';
      const theme = hostTheme || pageTheme;
      document.body.dataset.dshChatTheme = theme;
      if (nativeEmbedded && hostTheme) {
        root.dataset.dshHostTheme = theme;
        if (!root.classList.contains(theme)) {
          root.classList.remove(theme === 'dark' ? 'light' : 'dark');
          root.classList.add(theme);
        }
      }
    };
    const receive = (event: MessageEvent) => {
      if (!embedded || event.source !== window.parent || event.origin !== parentOrigin) return;
      if (event.data?.type === 'dsh:appearance' && ['dark', 'light'].includes(event.data.theme)) {
        hostTheme = event.data.theme;
        apply();
      }
    };
    const receiveNative = (event: Event) => {
      const theme = (event as CustomEvent<{ theme?: unknown }>).detail?.theme;
      if (nativeEmbedded && (theme === 'dark' || theme === 'light')) {
        hostTheme = theme;
        apply();
      }
    };
    const observer = new MutationObserver(apply);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    apply();
    window.addEventListener('dsh:appearance', receiveNative);
    window.addEventListener('message', receive);
    media.addEventListener('change', apply);
    if (embedded) window.parent.postMessage({ type: 'bisheng:ready' }, parentOrigin);
    return () => {
      observer.disconnect();
      delete document.body.dataset.dshChatTheme;
      window.removeEventListener('dsh:appearance', receiveNative);
      window.removeEventListener('message', receive);
      media.removeEventListener('change', apply);
    };
  }, []);
}
