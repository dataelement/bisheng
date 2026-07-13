import { useCallback, useRef, useState } from 'react';

/**
 * Width (px) below which the input toolbars collapse their button labels to
 * icons. Sized for the WIDEST locale (English labels — "Knowledge Space",
 * "Task mode" — are far longer than the Chinese ones), so labels collapse as a
 * group before any single one truncates, in every language. Tune here once;
 * both toolbars (AiChatInput, TaskModeInput) read this same value.
 */
export const TOOLBAR_COMPACT_THRESHOLD = 440;

/**
 * Report whether a container's inline width has dropped below `threshold`,
 * measured live via a ResizeObserver.
 *
 * Input toolbars collapse their button labels to icon-only when space runs
 * out. Viewport media queries are the wrong signal for that: the same viewport
 * width leaves very different room once the sidebar opens. This hook measures
 * the ACTUAL space available (the flex-1 toolbar column), so labels collapse
 * exactly when the box that holds them can no longer fit them.
 *
 * The observed element must be layout-sized (e.g. `flex-1`), NOT content-sized:
 * its width is then decided by the row, independent of whether labels are shown,
 * so hiding labels can't feed back into the measurement and oscillate.
 *
 * Returns a callback ref (re-attaches the observer across conditional remounts,
 * which a deps-based effect would miss) plus the current `compact` flag.
 */
export function useContainerCompact(threshold: number) {
  const [compact, setCompact] = useState(false);
  const observerRef = useRef<ResizeObserver | null>(null);

  const ref = useCallback(
    (el: HTMLElement | null) => {
      observerRef.current?.disconnect();
      observerRef.current = null;
      if (!el) return;
      const update = () => setCompact(el.clientWidth < threshold);
      update();
      const ro = new ResizeObserver(update);
      ro.observe(el);
      observerRef.current = ro;
    },
    [threshold],
  );

  return { ref, compact };
}
