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
}

/**
 * F027 §AC-17-client-补做: bottom sentinel that triggers `onLoad` when it
 * scrolls into view inside its nearest overflow:auto/scroll ancestor.
 * Callers should conditionally render this (e.g. `{hasMore && <LoadMore .../>}`)
 * so the sentinel disappears at end-of-list and the observer unbinds.
 */
export function LoadMore({ onLoad, loading }: LoadMoreProps) {
    const sentinelRef = useRef<HTMLDivElement>(null);
    // Keep `onLoad` in a ref so the observer (created once at mount) always
    // invokes the LATEST version — otherwise the closure freezes stale
    // cursor / hasMore values from first render.
    const onLoadRef = useRef(onLoad);
    useEffect(() => { onLoadRef.current = onLoad; }, [onLoad]);

    useEffect(() => {
        if (!sentinelRef.current) return;
        const root = findScrollableAncestor(sentinelRef.current);
        const observer = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) onLoadRef.current?.();
                });
            },
            { root, rootMargin: "0px", threshold: 0.1 },
        );
        observer.observe(sentinelRef.current);
        return () => observer.disconnect();
    }, []);

    return (
        <div ref={sentinelRef} className="flex h-10 w-full items-center justify-center text-xs text-[#86909c]">
            {loading ? "..." : ""}
        </div>
    );
}
