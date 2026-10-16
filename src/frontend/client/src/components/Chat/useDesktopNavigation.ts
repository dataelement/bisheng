import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { isDesktopEmbedded } from './desktopEmbedding';

/** Presentation-only navigation; the server still authorizes every conversation. */
export function useDesktopNavigation() {
  const navigate = useNavigate();
  useEffect(() => {
    if (!isDesktopEmbedded()) return;
    const receive = (event: Event) => {
      const path: unknown = (event as CustomEvent<{ path?: unknown }>).detail?.path;
      if (typeof path !== 'string' || !/^\/(?:c\/[a-zA-Z0-9_-]+|linsight\/[a-zA-Z0-9_-]+|chat\/[a-zA-Z0-9_-]+\/[a-zA-Z0-9_-]+\/(?:1|5|10))$/.test(path)) return;
      event.preventDefault();
      navigate(path);
    };
    window.addEventListener('dsh:navigate', receive);
    return () => window.removeEventListener('dsh:navigate', receive);
  }, [navigate]);
}
