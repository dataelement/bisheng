import {
  useState,
  useEffect,
  useLayoutEffect,
  useCallback,
  useRef,
  type RefObject,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { useElementSize } from "~/hooks/useElementSize";

interface UseResizablePanelOptions {
  storageKey: string;
  defaultRatio: number;
  minLeftWidth: number;
  minRightWidth: number;
  containerRef: RefObject<HTMLDivElement>;
  defaultLeftWidth?: (containerWidth: number) => number;
  enabled?: boolean;
}

/** One pixel belongs to the splitter; the two columns must both fit before dragging. */
export function useResizablePanel({
  storageKey,
  defaultRatio,
  minLeftWidth,
  minRightWidth,
  containerRef,
  defaultLeftWidth,
  enabled = true,
}: UseResizablePanelOptions) {
  const { width: containerWidth } = useElementSize(containerRef);
  const canSplit = containerWidth >= minLeftWidth + 1 + minRightWidth;
  const [ratio, setRatio] = useState<number | null>(() => {
    try {
      const parsed = Number(localStorage.getItem(storageKey));
      return parsed > 0 && parsed < 1 ? parsed : null;
    } catch {
      return null;
    }
  });
  const ratioRef = useRef(ratio);
  ratioRef.current = ratio;
  const [isResizing, setIsResizing] = useState(false);
  const baseWidth =
    ratio !== null
      ? ratio * containerWidth
      : (defaultLeftWidth?.(containerWidth) ?? defaultRatio * containerWidth);
  const leftWidth = canSplit
    ? Math.min(
        Math.max(Math.round(baseWidth), minLeftWidth),
        containerWidth - 1 - minRightWidth,
      )
    : containerWidth;
  const active = enabled && canSplit;

  useLayoutEffect(() => {
    if (!active) setIsResizing(false);
  }, [active]);

  const startResizing = useCallback(
    (event: ReactMouseEvent) => {
      if (!active) return;
      event.preventDefault();
      setIsResizing(true);
    },
    [active],
  );

  useEffect(() => {
    if (!isResizing || !active) return;
    const previousCursor = document.body.style.cursor;
    const previousSelection = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    const blockSelect = (event: Event) => event.preventDefault();
    const resize = (event: MouseEvent) => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect || rect.width < minLeftWidth + 1 + minRightWidth) return;
      event.preventDefault();
      const next = Math.min(
        Math.max(event.clientX - rect.left, minLeftWidth),
        rect.width - 1 - minRightWidth,
      );
      setRatio(next / rect.width);
    };
    const stop = () => {
      setIsResizing(false);
      try {
        if (ratioRef.current !== null)
          localStorage.setItem(storageKey, ratioRef.current.toFixed(4));
      } catch {
        /* Optional preference. */
      }
    };
    document.addEventListener("selectstart", blockSelect);
    window.addEventListener("mousemove", resize);
    window.addEventListener("mouseup", stop);
    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousSelection;
      document.removeEventListener("selectstart", blockSelect);
      window.removeEventListener("mousemove", resize);
      window.removeEventListener("mouseup", stop);
    };
  }, [
    isResizing,
    active,
    containerRef,
    minLeftWidth,
    minRightWidth,
    storageKey,
  ]);

  const resetToDefault = useCallback(() => {
    setRatio(null);
    try {
      localStorage.removeItem(storageKey);
    } catch {
      /* Optional preference. */
    }
  }, [storageKey]);

  return {
    leftWidth,
    containerWidth,
    canSplit,
    isResizing: isResizing && active,
    startResizing,
    resetToDefault,
  };
}
