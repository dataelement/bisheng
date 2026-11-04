import { useLayoutEffect, useState, type RefObject } from "react";

/** Observe the stable containing region, never the column compressed by its own panel. */
export function useElementSize(ref: RefObject<HTMLElement>) {
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => {
      const rect = element.getBoundingClientRect();
      const next = {
        width: Math.max(0, rect.width),
        height: Math.max(0, rect.height),
      };
      setSize((previous) =>
        previous.width === next.width && previous.height === next.height
          ? previous
          : next,
      );
    };
    measure();
    const observer =
      typeof ResizeObserver === "function"
        ? new ResizeObserver(measure)
        : undefined;
    observer?.observe(element);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [ref]);
  return size;
}
