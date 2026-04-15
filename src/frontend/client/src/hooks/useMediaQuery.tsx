import { useEffect, useState } from 'react';

export default function useMediaQuery(query: string) {
  const [matches, setMatches] = useState<boolean>(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return false;
    }
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }
    const media = window.matchMedia(query);
    setMatches(media.matches);

    const listener = (event: MediaQueryListEvent) => setMatches(event.matches);
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', listener);
      return () => media.removeEventListener('change', listener);
    }
    // Safari fallback
    media.addListener(listener);
    return () => media.removeListener(listener);
  }, [query]);

  return matches;
}
