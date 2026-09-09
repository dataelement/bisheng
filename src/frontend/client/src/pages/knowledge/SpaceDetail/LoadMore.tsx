import { useEffect, useRef } from "react";

/**
 * Walk up from `el` and return the nearest ancestor whose computed
 * overflow-y is `auto` / `scroll` / `overlay`. Fallback to `null` (viewport)
 * if no scrollable ancestor exists.
 *
 * Needed because IntersectionObserver defaults to `root: null` (viewport).
 * When the sentinel lives inside an in-page scroll container, scrolling
 * INSIDE that container never changes the sentinel's intersection with the
 * viewport, so the observer fires only at mount and never again. Passing
 * the scroll container as `root` makes intersection track in-container
 * scroll position instead.
 */
function findScrollableAncestor(el: Element | null): Element | null {
    let node: Element | null = el?.parentElement ?? null;
    while (node && node !== document.body && node !== document.documentElement) {
        const style = window.getComputedStyle(node);
        const overflowY = style.overflowY;
        if (overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay") {
            return node;
        }
        node = node.parentElement;
    }
    return null;
}

interface LoadMoreProps {
    onLoad: () => void;
    loading?: boolean;
    disabled?: boolean;
    loadingText?: string;
}

export function LoadMore({ onLoad, loading = false, disabled = false, loadingText = "" }: LoadMoreProps) {
    const sentinelRef = useRef<HTMLDivElement>(null);
    const onLoadRef = useRef(onLoad);
    const loadingRef = useRef(loading);
    const disabledRef = useRef(disabled);

    useEffect(() => { onLoadRef.current = onLoad; }, [onLoad]);
    useEffect(() => { loadingRef.current = loading; }, [loading]);
    useEffect(() => { disabledRef.current = disabled; }, [disabled]);

    useEffect(() => {
        if (!sentinelRef.current) return;
        const root = findScrollableAncestor(sentinelRef.current);
        const observer = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting && !loadingRef.current && !disabledRef.current) onLoadRef.current?.();
                });
            },
            { root, rootMargin: "0px", threshold: 0.1 },
        );
        observer.observe(sentinelRef.current);
        return () => observer.disconnect();
    }, [disabled, loading]);

    return (
        <div ref={sentinelRef} className="col-span-full flex h-10 w-full items-center justify-center text-xs text-text-3">
            {loading ? loadingText : ""}
        </div>
    );
}
