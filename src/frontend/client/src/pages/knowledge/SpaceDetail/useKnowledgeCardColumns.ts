import type { UseKnowledgeCardColumnsOptions } from "./knowledgeSpaceTypes";
import { useState, useRef, useLayoutEffect } from "react";
export function useKnowledgeCardColumns({
  displayFiles,
  viewMode,
}: UseKnowledgeCardColumnsOptions) {
  const cardGridRef = useRef<HTMLDivElement | null>(null);
  const calcCols = (w: number) => {
    if (w >= 1296) return 7;
    if (w >= 1024) return 6;
    if (w >= 768) return 5;
    if (w >= 600) return 4;
    if (w >= 480) return 3;
    if (w >= 320) return 2;
    return 1;
  };
  const [cardCols, setCardCols] = useState(() => {
    // Avoid first-paint "1 column" flash: start from viewport width, then refine with container width.
    const w =
      typeof window !== "undefined"
        ? document.documentElement?.clientWidth || window.innerWidth || 0
        : 0;
    return calcCols(w);
  });
  useLayoutEffect(() => {
    if (viewMode !== "card") return;
    const el = cardGridRef.current;

    if (!el) return;

    const scrollParent = el.parentElement as HTMLElement | null;
    const flexAncestor = scrollParent?.parentElement as HTMLElement | null;
    const getWidth = () =>
      scrollParent?.clientWidth ||
      el.clientWidth ||
      flexAncestor?.clientWidth ||
      0;

    let rafId: number | null = null;
    const apply = () => {
      const w = getWidth();
      if (!w) {
        rafId = window.requestAnimationFrame(apply);
        return;
      }
      const cols = calcCols(w);
      setCardCols((prev) => (prev === cols ? prev : cols));
    };

    apply();
    const ro =
      typeof ResizeObserver === "function"
        ? new ResizeObserver(() => apply())
        : undefined;
    ro?.observe(el);
    if (scrollParent) ro?.observe(scrollParent);
    if (flexAncestor) ro?.observe(flexAncestor);

    window.addEventListener("resize", apply);

    return () => {
      if (rafId) window.cancelAnimationFrame(rafId);
      window.removeEventListener("resize", apply);
      ro?.disconnect();
    };
  }, [viewMode, displayFiles.length]);

  return { cardGridRef, cardCols };
}
