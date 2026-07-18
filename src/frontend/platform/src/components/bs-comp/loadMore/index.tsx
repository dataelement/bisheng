import { useEffect, useRef } from "react";

/**
 * Walk up from `el` and return the nearest ancestor whose computed
 * overflow-y is `auto` / `scroll` / `overlay`. Fallback to `null` (browser
 * viewport) if no scrollable ancestor exists.
 *
 * F027: needed because IntersectionObserver defaults to `root: null`
 * (viewport). When the footer lives inside an in-page scroll container
 * (typical BiSheng table layout), scrolling INSIDE that container never
 * changes the footer's intersection with the viewport, so the observer
 * fires only at mount and never again. Passing the scroll container as
 * `root` makes intersection track in-container scroll position instead.
 */
function findScrollableAncestor(el: Element | null): Element | null {
    let node: Element | null = el?.parentElement ?? null
    while (node && node !== document.body && node !== document.documentElement) {
        const style = window.getComputedStyle(node)
        const overflowY = style.overflowY
        if (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') {
            return node
        }
        node = node.parentElement
    }
    return null
}

export default function LoadMore({ onScrollLoad }) {
    // scroll load
    const footerRef = useRef<HTMLDivElement>(null)
    // F027: keep ``onScrollLoad`` in a ref so the IntersectionObserver
    // callback (which is created once at mount with `[]` deps) always
    // invokes the LATEST version. Without this, the observer freezes the
    // first onScrollLoad it sees and subsequent scroll triggers use stale
    // cursor / hasMore values captured at first render.
    const cbRef = useRef(onScrollLoad)
    useEffect(() => { cbRef.current = onScrollLoad }, [onScrollLoad])

    useEffect(function () {
        const root = findScrollableAncestor(footerRef.current)
        console.log('[LoadMore] mount, footerRef=', footerRef.current, 'root=', root)
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                console.log('[LoadMore] intersection', { isIntersecting: entry.isIntersecting, ratio: entry.intersectionRatio })
                if (entry.isIntersecting) {
                    console.log('[LoadMore] FIRE onScrollLoad')
                    cbRef.current?.()
                }
            });
        }, {
            root,                // F027: scrollable ancestor; falls back to viewport
            rootMargin: '0px',
            threshold: 0.1,
        });

        observer.observe(footerRef.current);
        return () => {
            console.log('[LoadMore] unmount')
            footerRef.current && observer.unobserve(footerRef.current)
        }
    }, [])

    return <div ref={footerRef} style={{ height: 20 }}></div>
};
