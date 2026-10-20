import { useEffect, useRef, type RefObject } from 'react';
import { isDesktopEmbedded } from './desktopEmbedding';

/** A retained Chat document animates its own title when the host presents it. */
export function useWelcomeTransition(title: RefObject<HTMLHeadingElement>) {
  const animation = useRef<Animation | null>(null);
  useEffect(() => {
    if (!isDesktopEmbedded()) return;
    const enter = () => {
      animation.current?.cancel();
      const element = title.current;
      if (!element || !element.getClientRects().length || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      animation.current = element.animate([
        { transform: 'translateY(-6px)', opacity: 0 },
        { transform: 'translateY(0)', opacity: 1 },
      ], { duration: 180, easing: 'cubic-bezier(.23,1,.32,1)' });
    };
    window.addEventListener('dsh:welcome-enter', enter);
    return () => {
      window.removeEventListener('dsh:welcome-enter', enter);
      animation.current?.cancel();
    };
  }, [title]);
}
