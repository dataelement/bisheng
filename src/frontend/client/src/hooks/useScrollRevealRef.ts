import { useCallback, useRef } from 'react';

/**
 * Ref callback that writes `data-scrolling='true'` to the element while it's actively
 * scrolling, then removes it after `hideAfterMs`. Pairs with two CSS utilities in style.css:
 *  - `scrollbar-on-scroll`: thumb visible only while scrolling (all pointer types).
 *  - `scrollbar-on-hover`: thumb visible on hover (mouse) / scroll (touch) — uses the
 *    attribute on touch only.
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
