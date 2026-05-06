import { useCallback, useRef } from 'react';

/**
 * Ref callback for elements with `scrollbar-on-hover`: on coarse pointer / touch viewports,
 * CSS shows the scrollbar only while `[data-scrolling='true']` (see style.css).
 * Mouse + fine pointer keeps hover-based scrollbar behavior.
 */
export function useScrollRevealRef<T extends HTMLElement>(hideAfterMs = 700) {
  const cleanupRef = useRef<(() => void) | undefined>(undefined);

  return useCallback(
    (node: T | null) => {
      cleanupRef.current?.();
      cleanupRef.current = undefined;
      if (!node) {
        return;
      }

      let timeoutId: ReturnType<typeof setTimeout> | undefined;
      const onScroll = () => {
        node.setAttribute('data-scrolling', 'true');
        if (timeoutId !== undefined) clearTimeout(timeoutId);
        timeoutId = setTimeout(() => {
          node.removeAttribute('data-scrolling');
          timeoutId = undefined;
        }, hideAfterMs);
      };

      node.addEventListener('scroll', onScroll, { passive: true });
      cleanupRef.current = () => {
        node.removeEventListener('scroll', onScroll);
        if (timeoutId !== undefined) clearTimeout(timeoutId);
        node.removeAttribute('data-scrolling');
      };
    },
    [hideAfterMs],
  );
}
