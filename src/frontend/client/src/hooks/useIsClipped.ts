import { useLayoutEffect, useRef, useState } from 'react';

/** Shared with the original skill picker: show full text only when a line clips. */
export function useIsClipped<T extends HTMLElement>(text?: string) {
  const ref = useRef<T | null>(null);
  const [clipped, setClipped] = useState(false);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) { setClipped(false); return; }
    // Absorb sub-pixel rounding when a line fits exactly.
    const measure = () => setClipped(element.scrollWidth > element.clientWidth + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text]);

  return [ref, clipped] as const;
}
