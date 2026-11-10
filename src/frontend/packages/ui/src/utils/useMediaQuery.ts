import * as React from 'react';

/**
 * The shared 576px phone breakpoint (基础-多端适配原则.md) — components that
 * switch layout on a phone read it from here rather than picking their own.
 */
export const PHONE_QUERY = '(max-width: 575.98px)';

/** Live `matchMedia` result; `false` until mounted (and outside a browser). */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = React.useState(false);

  React.useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }
    const list = window.matchMedia(query);
    const sync = () => setMatches(list.matches);
    sync();
    list.addEventListener('change', sync);
    return () => list.removeEventListener('change', sync);
  }, [query]);

  return matches;
}
