import { useLayoutEffect, useState } from 'react';
import { CLIENT_MARKDOWN_DEFAULTS } from './markdownConfig';
/** Same first-frame, resize and older Safari behavior as the client media hook. */
function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(query).matches);
  useLayoutEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const media = window.matchMedia(query);
    setMatches(media.matches);
    const listener = (event: MediaQueryListEvent) => setMatches(event.matches);
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', listener);
      return () => media.removeEventListener('change', listener);
    }
    media.addListener(listener);
    return () => media.removeListener(listener);
  }, [query]);
  return matches;
}
export function useMarkdownViewport() {
  return { isMobileLayout: useMediaQuery(CLIENT_MARKDOWN_DEFAULTS.mobileQuery), finePointer: useMediaQuery(CLIENT_MARKDOWN_DEFAULTS.finePointerQuery) };
}
