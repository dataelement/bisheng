import { RefObject, useEffect } from "react";

// How much horizontal room to leave free at the right of the visible area.
//  • idle: just a small breathing gap to the panel edge.
//  • hovered: enough room for the more-button (sticky at the right) so the
//    name's ellipsis lands *before* the button instead of under it.
const EDGE_GUTTER = 16;
const HOVER_GUTTER = 44;

/**
 * Dynamic, scroll-following ellipsis for the sidebar name labels.
 *
 * Each name is rendered as an invisible natural-width spacer (which drives the
 * row's horizontal scroll width) plus an absolutely-positioned visible overlay
 * tagged `[data-ellipsis-text]`. This hook sets each overlay's `max-width` to the
 * distance between its left edge and the scroll viewport's right edge (minus a
 * gutter), so the ellipsis always lands at the current viewport edge. As the user
 * scrolls horizontally the overlay's left edge moves, the available width grows,
 * and more of the name is revealed — i.e. the truncation point follows the scroll.
 *
 * Pass the scrolling container's ref. Rows that should reserve extra room for the
 * more-button on hover must carry `[data-ee-row]` (a `:hover` check widens the
 * gutter for that row only).
 */
/**
 * @param deps Extra effect dependencies. Pass these when the scroll container is
 *   mounted conditionally (e.g. inside a Radix Dialog that only renders its
 *   content while open) so the observers re-attach once the container exists —
 *   without them the effect runs once at mount, finds a null ref, and bails.
 */
export function useDynamicEllipsis(containerRef: RefObject<HTMLElement>, deps: unknown[] = []) {
    useEffect(() => {
        const container = containerRef.current;
        if (!container || typeof window === "undefined") return;

        let raf = 0;

        const run = () => {
            raf = 0;
            const containerRight = container.getBoundingClientRect().right;
            const nodes = container.querySelectorAll<HTMLElement>("[data-ellipsis-text]");

            // Read phase — measure every overlay before writing to avoid layout thrash.
            const items: Array<{ el: HTMLElement; left: number; hovered: boolean }> = [];
            nodes.forEach((el) => {
                const left = el.getBoundingClientRect().left;
                const row = el.closest<HTMLElement>("[data-ee-row]");
                const hovered = !!row && row.matches(":hover");
                items.push({ el, left, hovered });
            });

            // Write phase — setting max-width on absolutely-positioned overlays does
            // not reflow their siblings, so this stays cheap.
            for (const { el, left, hovered } of items) {
                const gutter = hovered ? HOVER_GUTTER : EDGE_GUTTER;
                el.style.maxWidth = `${Math.max(0, containerRight - left - gutter)}px`;
            }
        };

        const schedule = () => {
            if (!raf) raf = requestAnimationFrame(run);
        };

        schedule();

        container.addEventListener("scroll", schedule, { passive: true });
        // Hover changes which row reserves the wider (more-button) gutter.
        container.addEventListener("pointerover", schedule);
        container.addEventListener("pointerout", schedule);

        // Panel resize (drag-to-resize / window) and content size changes
        // (folder tree expand/collapse, data load) both change the available width.
        const ro = new ResizeObserver(schedule);
        ro.observe(container);

        // Catch DOM additions/removals (expand/collapse, list refresh) so freshly
        // mounted overlays get measured. We only watch childList, never attributes,
        // so our own max-width writes can't re-trigger this.
        const mo = new MutationObserver(schedule);
        mo.observe(container, { childList: true, subtree: true });

        return () => {
            if (raf) cancelAnimationFrame(raf);
            container.removeEventListener("scroll", schedule);
            container.removeEventListener("pointerover", schedule);
            container.removeEventListener("pointerout", schedule);
            ro.disconnect();
            mo.disconnect();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [containerRef, ...deps]);
}
