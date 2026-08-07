/**
 * useMarkdownOutline — wiring for the markdown preview's outline rail.
 *
 * Owns everything stateful: reading headings back out of the rendered markdown,
 * tracking which section the reader is in, and measuring the scroll container
 * so the rail can size and centre itself. MarkdownOutline.tsx stays a pure
 * presentation component (same split as WorkspacePanel ⇄ useWorkspacePanel).
 */
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import {
    collectHeadings,
    getScrollParent,
    headingsEqual,
    pickActiveIndex,
    scrollHeadingIntoView,
    solveRailLayout,
    type OutlineHeading,
} from './markdownOutlineUtils';

export function useMarkdownOutline(contentRef: RefObject<HTMLElement>, contentKey: string) {
    const [headings, setHeadings] = useState<OutlineHeading[]>([]);
    const [activeIndex, setActiveIndex] = useState(0);
    const [viewportHeight, setViewportHeight] = useState(0);
    const scrollerRef = useRef<HTMLElement | null>(null);
    const headingsRef = useRef<OutlineHeading[]>([]);
    headingsRef.current = headings;

    // Read the outline out of the rendered document, then keep watching it. A
    // one-shot scan is not enough: markdown keeps settling after the first paint
    // (async image resolution, a live run appending sections), and a scan that
    // lands too early would leave the outline permanently empty.
    useEffect(() => {
        const root = contentRef.current;
        if (!root) {
            return undefined;
        }
        let frame = 0;
        const scan = () => {
            frame = 0;
            const next = collectHeadings(root);
            setHeadings((prev) => (headingsEqual(prev, next) ? prev : next));
        };
        scan();
        // Coalesce bursts of mutations into one scan per frame.
        const observer = new MutationObserver(() => {
            if (frame === 0) {
                frame = requestAnimationFrame(scan);
            }
        });
        observer.observe(root, { childList: true, subtree: true, characterData: true });
        return () => {
            observer.disconnect();
            if (frame !== 0) {
                cancelAnimationFrame(frame);
            }
        };
    }, [contentRef, contentKey]);

    // Track the scroll container: it drives both the active section and the
    // rail's height budget.
    useEffect(() => {
        const scroller = getScrollParent(contentRef.current);
        scrollerRef.current = scroller;
        if (!scroller) {
            return undefined;
        }

        let frame = 0;
        const measureActive = () => {
            frame = 0;
            setActiveIndex(pickActiveIndex(headingsRef.current, scroller));
        };
        const onScroll = () => {
            // rAF-throttled: scroll fires far more often than the rail can change.
            if (frame === 0) {
                frame = requestAnimationFrame(measureActive);
            }
        };

        scroller.addEventListener('scroll', onScroll, { passive: true });
        const observer = new ResizeObserver(() => {
            setViewportHeight(scroller.clientHeight);
            onScroll();
        });
        observer.observe(scroller);
        setViewportHeight(scroller.clientHeight);
        measureActive();

        return () => {
            scroller.removeEventListener('scroll', onScroll);
            observer.disconnect();
            if (frame !== 0) {
                cancelAnimationFrame(frame);
            }
        };
    }, [contentRef, headings]);

    const layout = useMemo(
        () => solveRailLayout(headings.map((h) => h.depth), viewportHeight),
        [headings, viewportHeight],
    );

    const scrollTo = useCallback((index: number) => {
        scrollHeadingIntoView(headingsRef.current[index]?.el, scrollerRef.current);
    }, []);

    /** Ticks visible on the collapsed rail (deep levels drop out when dense). */
    const railHeadings = useMemo(
        () => headings.filter((h) => h.depth <= layout.maxDepth),
        [headings, layout.maxDepth],
    );

    // When the current heading is one the rail hides, the nearest shown ancestor
    // lights up instead — the reader still sees roughly where they are.
    const railActiveIndex = useMemo(() => {
        let found = 0;
        railHeadings.forEach((h, i) => {
            if (h.index <= activeIndex) {
                found = i;
            }
        });
        return found;
    }, [railHeadings, activeIndex]);

    return {
        headings,
        activeIndex,
        railHeadings,
        railActiveIndex,
        gap: layout.gap,
        /** Rail is vertically centred in the scrollport. */
        railTop: viewportHeight / 2,
        /** Cap the expanded card to the panel, not the browser window — the
         *  preview is often a short docked card inside a taller viewport. */
        maxCardHeight: Math.max(160, Math.min(420, viewportHeight - 48)),
        scrollTo,
    };
}
