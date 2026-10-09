/**
 * F071: keep the compare open/close animation off the layout hot path.
 *
 * Entering or leaving the report ↔ source compare view animates the docked
 * workspace's width (docked clamp() ↔ the whole row). Left alone, every frame of
 * that 300ms transition re-wraps three text-heavy trees: the chat column (flex-1,
 * shrinking or growing), the report pane (a % of the panel) and the source pane
 * (flex-1) — plus the source document starts rendering on top. That is the jank.
 *
 * While the transition runs this hook pins both boxes to their END widths, so the
 * animating wrapper only clips them (overflow-hidden) instead of re-laying them
 * out: the report slides over and the source is uncovered, the chat column fades
 * at a fixed width. The pins drop once the transition is over — by then the live
 * layout resolves to the same widths, so nothing moves. `entering` also tells the
 * caller to hold the source document's render until the panel has settled.
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
    /** Fixed width for the chat column's children (it fades while the panel moves). */
    chat: number;
    /** Fixed width for the docked panel's inner card. */
    panel: number;
    entering: boolean;
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
            // Entering: hold the chat at the width it has now while it fades out.
            // Leaving: lay it out once at the width it is growing back to.
            chat: comparing ? chatRef.current?.getBoundingClientRect().width ?? row - target : row - target,
            // Collapsing to nothing: keep the card as it is and just clip it.
            panel: target > 0 ? target - WRAPPER_PADDING_X : panelRef.current?.getBoundingClientRect().width ?? 0,
            entering: comparing,
        });
        const timer = setTimeout(() => setFreeze(null), COMPARE_SETTLE_MS);
        return () => clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps -- panelRef is a stable ref object
    }, [comparing]);

    return {
        rowRef,
        chatRef,
        /** Style for the chat column: pins its children through a CSS variable. */
        chatStyle: freeze ? ({ '--compare-freeze-w': `${freeze.chat}px` } as React.CSSProperties) : undefined,
        panelStyle: freeze ? { minWidth: freeze.panel, width: freeze.panel } : undefined,
        /** True while the panel is still opening into the compare view. */
        entering: !!freeze?.entering,
    };
}
