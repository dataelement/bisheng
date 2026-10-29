import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { isDesktopEmbedded } from './desktopEmbedding';

/** Explicit presentation routes; APIs retain authorization ownership. */
export function isDesktopNavigationPath(path: string): boolean {
  return /^\/settings\/(?:account|desktop-usage|ai-access|my-tasks|my-requests|notifications)\?dshSettings=1$/.test(path)
    || /^\/(?:c\/[a-zA-Z0-9_-]+|linsight\/[a-zA-Z0-9_-]+|chat\/[a-zA-Z0-9_-]+\/[a-zA-Z0-9_-]+\/(?:1|5|10)|knowledge|channel|apps(?:\/[a-zA-Z0-9_-]+)*|skills|square)$/.test(path)
    || /^\/menu-unavailable\?plugin=(?:home|knowledge_space|subscription|apps)$/.test(path);
}

/** Presentation-only navigation; the server still authorizes every conversation. */
export function useDesktopNavigation() {
  const navigate = useNavigate();
  useEffect(() => {
    if (!isDesktopEmbedded()) return;
    const receive = (event: Event) => {
      const path: unknown = (event as CustomEvent<{ path?: unknown }>).detail?.path;
      if (typeof path !== 'string' || !isDesktopNavigationPath(path)) return;
      event.preventDefault();
      navigate(path);
    };
    window.addEventListener('dsh:navigate', receive);
    return () => window.removeEventListener('dsh:navigate', receive);
  }, [navigate]);
}
