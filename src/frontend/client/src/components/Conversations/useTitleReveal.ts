import { useEffect, useRef } from 'react';

/** Reveal overflowing titles at the Harness row speed, respecting reduced motion. */
export function useTitleReveal(title: string) {
  const ref = useRef<HTMLSpanElement>(null);
  const frame = useRef(0);
  const reset = () => {
    cancelAnimationFrame(frame.current);
    if (ref.current) ref.current.scrollLeft = 0;
  };
  useEffect(() => reset, [title]);
  const reveal = () => {
    reset();
    const element = ref.current;
    if (!element) return;
    const distance = element.scrollWidth - element.clientWidth;
    if (distance <= 8) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { element.scrollLeft = distance; return; }
    let start: number | undefined;
    const tick = (now: number) => {
      start ??= now;
      element.scrollLeft = Math.min(distance, (now - start) * .03);
      if (element.scrollLeft < distance) frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
  };
  return { ref, reveal, reset };
}
