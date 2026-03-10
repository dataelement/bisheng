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
 * Used by ChannelLayout (article list / detail) and FullScreenArticle (article / AI panel).
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

    // Start drag
    const startResizing = useCallback((e: React.MouseEvent) => {
        e.preventDefault();
        setIsResizing(true);
    }, []);

    // Stop drag
    const stopResizing = useCallback(() => {
        setIsResizing(false);
        localStorage.setItem(storageKey, leftWidth.toString());
    }, [storageKey, leftWidth]);

    // Dragging
    const resize = useCallback(
        (e: MouseEvent) => {
            if (!isResizing || !containerRef.current) return;

            const containerRect = containerRef.current.getBoundingClientRect();
            const newLeftWidth = e.clientX - containerRect.left;

            // Restrict minimum width
            if (
                newLeftWidth >= minLeftWidth &&
                containerRect.width - newLeftWidth >= minRightWidth
            ) {
                setLeftWidth(newLeftWidth);
            }
        },
        [isResizing, containerRef, minLeftWidth, minRightWidth]
    );

    useEffect(() => {
        if (isResizing) {
            window.addEventListener("mousemove", resize);
            window.addEventListener("mouseup", stopResizing);
        } else {
            window.removeEventListener("mousemove", resize);
            window.removeEventListener("mouseup", stopResizing);
        }
        return () => {
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
