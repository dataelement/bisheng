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
 *
 * The pins are written straight onto the two elements, not held in React state:
 * releasing one must not re-render the whole chat view right as the panel lands
 * (that re-render alone measured ~85ms).
 */
import { useLayoutEffect, useRef } from 'react';

/** Wrapper transition is duration-300; leave a frame of slack. */
export const COMPARE_SETTLE_MS = 340;
/** The docked wrapper's p-1 — the inner card is the wrapper width minus this. */
const WRAPPER_PADDING_X = 8;
/** Read by the chat column's `[&>*]:min-w-[var(--compare-freeze-w,0px)]`. */
export const CHAT_FREEZE_VAR = '--compare-freeze-w';

/** Mirrors the docked wrapper's `clamp(440px, 46%, 720px)` inline width. */
function dockedWidth(rowWidth: number): number {
    return Math.min(Math.max(440, rowWidth * 0.46), 720);
}

function pinChat(el: HTMLElement | null, width: number | null) {
    if (!el) return;
    if (width == null) el.style.removeProperty(CHAT_FREEZE_VAR);
    else el.style.setProperty(CHAT_FREEZE_VAR, `${width}px`);
}

function pinPanel(el: HTMLElement | null, width: number | null) {
    if (!el) return;
    el.style.width = width == null ? '' : `${width}px`;
    el.style.minWidth = width == null ? '' : `${width}px`;
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
        const chat = chatRef.current;
        const panel = panelRef.current;
        const row = rowRef.current?.getBoundingClientRect().width ?? 0;
        if (!enabledRef.current || !row) {
            pinChat(chat, null);
            pinPanel(panel, null);
            return undefined;
        }
        const target = !openRef.current ? 0 : comparing ? row : dockedWidth(row);
        // Entering: the width the chat has now. Leaving: the width it grows back to.
        // Measure before pinning — the pins change what is measured.
        const chatWidth = comparing ? chat?.getBoundingClientRect().width ?? row - target : row - target;
        // Collapsing to nothing: keep the card as it is and just clip it.
        const panelWidth = target > 0 ? target - WRAPPER_PADDING_X : panel?.getBoundingClientRect().width ?? 0;
        pinChat(chat, chatWidth);
        pinPanel(panel, panelWidth);

        const timer = setTimeout(() => {
            pinPanel(panel, null);
            // While compare stays open the chat pin stays: releasing it would lay
            // the hidden messages out at ~0px. After closing, the live width is the pin.
            if (!comparing) pinChat(chat, null);
        }, COMPARE_SETTLE_MS);
        return () => clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps -- panelRef is a stable ref object
    }, [comparing]);

    return { rowRef, chatRef };
}
