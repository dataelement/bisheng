import React, { useState, useEffect, useCallback } from "react";

interface UseResizablePanelOptions {
    /** localStorage key to persist width */
    storageKey: string;
    /** Default width if no persisted value */
    defaultWidth: number;
    /** Minimum width for the left panel */
    minLeftWidth: number;
    /** Minimum width for the right panel */
    minRightWidth: number;
    /** Ref to the container element for calculating bounds */
    containerRef: React.RefObject<HTMLDivElement>;
}

/**
 * Shared hook for draggable split-panel resize logic.
 * Handles mouse-tracking at the document level so the divider follows
 * the cursor even when dragging quickly or over iframes.
 */
export function useResizablePanel({
    storageKey,
    defaultWidth,
    minLeftWidth,
    minRightWidth,
    containerRef,
}: UseResizablePanelOptions) {
    const [leftWidth, setLeftWidth] = useState<number>(() => {
        const saved = localStorage.getItem(storageKey);
        return saved ? parseInt(saved, 10) : defaultWidth;
    });
    const [isResizing, setIsResizing] = useState(false);

    // Start drag — lock cursor & disable text selection globally
    const startResizing = useCallback((e: React.MouseEvent) => {
        e.preventDefault();
        setIsResizing(true);
        document.body.style.userSelect = "none";
        document.body.style.cursor = "col-resize";
    }, []);

    // Stop drag — restore cursor & persist width
    const stopResizing = useCallback(() => {
        setIsResizing(false);
        document.body.style.userSelect = "";
        document.body.style.cursor = "";
        setLeftWidth((w) => {
            localStorage.setItem(storageKey, w.toString());
            return w;
        });
    }, [storageKey]);

    // Handle drag movement
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
                setLeftWidth(newLeftWidth);
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
        setLeftWidth,
        isResizing,
        startResizing,
    };
}
