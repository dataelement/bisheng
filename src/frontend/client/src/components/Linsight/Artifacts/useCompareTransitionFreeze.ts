/**
 * F071: keep the report ↔ source compare view off the layout hot path.
 *
 * Opening a cited source animates the docked workspace's width (docked clamp() →
 * the whole row) while the chat column, a flex-1 sibling, is squeezed to zero and
 * faded out. Left alone that costs twice:
 * - every frame of the 300ms transition re-wraps the chat column and the report
 *   pane (a % of the panel) at an in-between width;
 * - worst of all, the chat column ends at ~0px wide, and laying every message
 *   out one character per line freezes the page for close to a second (measured
 *   on test: a single ~900ms task right after the panel arrives).
 *
 * So the chat column's children keep the width they had before compare opened
 * for as long as compare stays open — the column is invisible then, it only
 * clips them — and get the width they are growing back to while compare closes.
 * The panel card is pinned to its end width for the length of each transition,
 * so the animating wrapper uncovers the report and source instead of re-laying
 * them out. Every pin drops once the layout it stands in for is the real one.
 */
import { useLayoutEffect, useRef, useState } from 'react';

/** Wrapper transition is duration-300; leave a frame of slack. */
export const COMPARE_SETTLE_MS = 340;
/** The docked wrapper's p-1 — the inner card is the wrapper width minus this. */
const WRAPPER_PADDING_X = 8;

/** Mirrors the docked wrapper's `clamp(440px, 46%, 720px)` inline width. */
function dockedWidth(rowWidth: number): number {
    return Math.min(Math.max(440, rowWidth * 0.46), 720);
}

interface CompareFreeze {
    /** Fixed width for the chat column's children. */
    chat: number;
    /** Fixed width for the docked panel's inner card; null once settled. */
    panel: number | null;
}

export function useCompareTransitionFreeze(
    comparing: boolean,
    open: boolean,
    enabled: boolean,
    /** The docked panel's inner card (already owned by the host for fullscreen). */
    panelRef: React.RefObject<HTMLDivElement>,
) {
    const rowRef = useRef<HTMLDivElement>(null);
    const chatRef = useRef<HTMLDivElement>(null);
    const [freeze, setFreeze] = useState<CompareFreeze | null>(null);
    const prevComparing = useRef(comparing);
    // Read through refs so the effect re-runs (and re-arms its timer) only on
    // a compare toggle, never on an unrelated open/layout change mid-transition.
    const openRef = useRef(open);
    const enabledRef = useRef(enabled);
    openRef.current = open;
    enabledRef.current = enabled;

    // Layout effect: the pins must be in place before the first frame of the
    // transition paints, or that frame is laid out at the in-between width.
    useLayoutEffect(() => {
        if (prevComparing.current === comparing) return undefined;
        prevComparing.current = comparing;
        const row = rowRef.current?.getBoundingClientRect().width ?? 0;
        if (!enabledRef.current || !row) {
            setFreeze(null);
            return undefined;
        }
        const target = !openRef.current ? 0 : comparing ? row : dockedWidth(row);
        setFreeze({
            // Entering: the width the chat has now. Leaving: the width it grows back to.
            chat: comparing ? chatRef.current?.getBoundingClientRect().width ?? row - target : row - target,
            // Collapsing to nothing: keep the card as it is and just clip it.
            panel: target > 0 ? target - WRAPPER_PADDING_X : panelRef.current?.getBoundingClientRect().width ?? 0,
        });
        const timer = setTimeout(() => {
            // While compare stays open the chat pin stays: releasing it would lay
            // the hidden messages out at ~0px. After closing, the live width is the pin.
            setFreeze((current) => (comparing && current ? { chat: current.chat, panel: null } : null));
        }, COMPARE_SETTLE_MS);
        return () => clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps -- panelRef is a stable ref object
    }, [comparing]);

    return {
        rowRef,
        chatRef,
        /** Style for the chat column: pins its children through a CSS variable. */
        chatStyle: freeze ? ({ '--compare-freeze-w': `${freeze.chat}px` } as React.CSSProperties) : undefined,
        panelStyle: freeze?.panel != null ? { minWidth: freeze.panel, width: freeze.panel } : undefined,
    };
}
