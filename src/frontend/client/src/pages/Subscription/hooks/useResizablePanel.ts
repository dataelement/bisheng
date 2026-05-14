import React, { useState, useEffect, useCallback, useRef } from "react";

interface UseResizablePanelOptions {
    /** localStorage key to persist the split ratio (0–1) */
    storageKey: string;
    /** Default ratio for the left panel (0–1), e.g. 0.5 = 50% */
    defaultRatio: number;
    /** Minimum width for the left panel (px) */
    minLeftWidth: number;
    /** Minimum width for the right panel (px) */
    minRightWidth: number;
    /** Ref to the container element for calculating bounds */
    containerRef: React.RefObject<HTMLDivElement>;
}

/**
 * Shared hook for draggable split-panel resize logic.
 * Persists the split position as a **ratio** (0–1) so the layout
 * stays proportional across different screen sizes.
 */
export function useResizablePanel({
    storageKey,
    defaultRatio,
    minLeftWidth,
    minRightWidth,
    containerRef,
}: UseResizablePanelOptions) {
    // Store ratio (0–1) internally; derive pixel width on render
    const [ratio, setRatio] = useState<number>(() => {
        const saved = localStorage.getItem(storageKey);
        if (saved) {
            const parsed = parseFloat(saved);
            if (!isNaN(parsed) && parsed > 0 && parsed < 1) return parsed;
        }
        return defaultRatio;
    });
    const [isResizing, setIsResizing] = useState(false);

    // Force a re-render after mount so containerRef.current is available for width calculation
    const [mounted, setMounted] = useState(false);
    useEffect(() => { setMounted(true); }, []);

    // Convert ratio to pixel width, clamped by min constraints
    const getLeftWidth = useCallback((): number => {
        const containerWidth = containerRef.current?.getBoundingClientRect().width ?? 0;
        if (containerWidth === 0) return minLeftWidth;

        let px = Math.round(ratio * containerWidth);
        // Enforce minimum constraints
        px = Math.max(px, minLeftWidth);
        px = Math.min(px, containerWidth - minRightWidth);
        return px;
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ratio, containerRef, minLeftWidth, minRightWidth, mounted]);

    const leftWidth = getLeftWidth();

    // Start drag — lock cursor & disable text selection globally
    const startResizing = useCallback((e: React.MouseEvent) => {
        e.preventDefault();
        setIsResizing(true);
        document.body.style.userSelect = "none";
        document.body.style.cursor = "col-resize";
    }, []);

    // Stop drag — restore cursor & persist ratio
    const stopResizing = useCallback(() => {
        setIsResizing(false);
        document.body.style.userSelect = "";
        document.body.style.cursor = "";
        setRatio((r) => {
            localStorage.setItem(storageKey, r.toFixed(4));
            return r;
        });
    }, [storageKey]);

    // Handle drag movement — compute new ratio from mouse position
    const resize = useCallback(
        (e: MouseEvent) => {
            if (!containerRef.current) return;
            e.preventDefault();

            const rect = containerRef.current.getBoundingClientRect();
            const newLeftWidth = e.clientX - rect.left;

            if (
                newLeftWidth >= minLeftWidth &&
                rect.width - newLeftWidth >= minRightWidth
            ) {
                setRatio(newLeftWidth / rect.width);
            }
        },
        [containerRef, minLeftWidth, minRightWidth]
    );

    // Attach / detach listeners whenever isResizing changes
    useEffect(() => {
        if (!isResizing) return;

        // Block text selection events during drag
        const blockSelect = (e: Event) => e.preventDefault();
        document.addEventListener("selectstart", blockSelect);
        window.addEventListener("mousemove", resize);
        window.addEventListener("mouseup", stopResizing);

        return () => {
            document.removeEventListener("selectstart", blockSelect);
            window.removeEventListener("mousemove", resize);
            window.removeEventListener("mouseup", stopResizing);
        };
    }, [isResizing, resize, stopResizing]);

    return {
        leftWidth,
        isResizing,
        startResizing,
    };
}
