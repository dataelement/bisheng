/**
 * Outline (table-of-contents) helpers for the markdown deliverable preview.
 *
 * Pure DOM/math functions only — no React — so they stay unit-testable. The
 * rendering side lives in MarkdownOutline.tsx and the wiring in
 * useMarkdownOutline.ts.
 *
 * Headings are read back from the RENDERED DOM rather than parsed out of the
 * markdown source: `rehypeSlug` already stamps a stable `id` on every heading
 * (Markdown.tsx), and reading the DOM keeps the outline 1:1 with what's on
 * screen — `#` inside fenced code, setext headings and slug de-dupe suffixes
 * all line up for free.
 */

/** One entry of the outline. `level` is the raw h-tag depth (1..6). */
export interface OutlineHeading {
    id: string;
    text: string;
    level: number;
    /** Depth after normalization (1 = shallowest level present in the doc). */
    depth: number;
    /** Position in the full outline — stays valid when the rail hides deep levels. */
    index: number;
    el: HTMLElement;
}

/** Tick length per normalized depth. The steps are wide apart on purpose: at
 *  2px tall and ~50% opacity, anything subtler stops reading as a staircase. */
export const TICK_LENGTHS = [18, 11, 6, 4] as const;
/** Vertical breathing room kept free above and below the rail, total. */
const RAIL_VERTICAL_PADDING = 96;
const TICK_HEIGHT = 2;
const MAX_GAP = 6;
const MIN_GAP = 2;
/** A heading counts as "current" once its top passes this band of the viewport. */
const ACTIVE_BAND = 24;

/** Nearest scrollable ancestor, or null when nothing up the chain scrolls. */
export function getScrollParent(el: HTMLElement | null): HTMLElement | null {
    let node = el?.parentElement ?? null;
    while (node) {
        const { overflowY } = window.getComputedStyle(node);
        if (overflowY === 'auto' || overflowY === 'scroll') {
            return node;
        }
        node = node.parentElement;
    }
    return null;
}

/**
 * Collapse the raw h-levels to a 1-based depth using the shallowest level the
 * document actually uses. Reports routinely start at `##` (or spend `#` on the
 * title only) — without this the whole staircase shifts right and stops
 * describing the document's shape.
 */
export function normalizeLevels<T extends { level: number }>(items: T[]): (T & { depth: number })[] {
    if (items.length === 0) {
        return [];
    }
    const shallowest = Math.min(...items.map((h) => h.level));
    return items.map((h) => ({ ...h, depth: h.level - shallowest + 1 }));
}

/** Read every heading inside a rendered `.bs-mkdown` container, in document order. */
export function collectHeadings(root: HTMLElement | null): OutlineHeading[] {
    if (!root) {
        return [];
    }
    const nodes = Array.from(root.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6'));
    const raw = nodes
        .map((el) => ({
            id: el.id,
            text: (el.textContent ?? '').trim(),
            level: Number(el.tagName.slice(1)),
            el,
        }))
        // No id means nothing to scroll to; no text means nothing to label.
        .filter((h) => h.id !== '' && h.text !== '');
    return normalizeLevels(raw).map((h, index) => ({ ...h, index }));
}

/**
 * Do two scans describe the same outline? The scan re-runs on every DOM change
 * inside the document (async images, a live run appending content), and most of
 * those leave the headings untouched — comparing lets the hook keep the old
 * array and skip a render.
 */
export function headingsEqual(a: OutlineHeading[], b: OutlineHeading[]): boolean {
    return (
        a.length === b.length &&
        a.every((h, i) => h.id === b[i].id && h.text === b[i].text && h.depth === b[i].depth)
    );
}

export interface RailLayout {
    /** Gap between ticks, in px. */
    gap: number;
    /** Deepest depth still shown on the rail; deeper headings are dropped. */
    maxDepth: number;
}

/**
 * Fit the ticks into the available height. Tighten the gap first; when even the
 * minimum gap overflows, drop the deepest level and try again. Depth 1–2 is
 * never dropped — past that the rail just gets dense, which still reads better
 * than a rail that runs off the panel.
 */
export function solveRailLayout(depths: number[], availableHeight: number): RailLayout {
    let maxDepth = depths.length > 0 ? Math.max(...depths) : 1;
    const usable = availableHeight - RAIL_VERTICAL_PADDING;
    // Not measured yet (or a panel too short to reason about) — show everything
    // at the roomy gap; the ResizeObserver will re-solve as soon as it lands.
    if (usable <= 0) {
        return { gap: MAX_GAP, maxDepth };
    }

    for (;;) {
        const count = depths.filter((d) => d <= maxDepth).length;
        if (count <= 1) {
            return { gap: MAX_GAP, maxDepth };
        }
        const gap = (usable - count * TICK_HEIGHT) / (count - 1);
        if (gap >= MIN_GAP || maxDepth <= 2) {
            return { gap: Math.min(MAX_GAP, Math.max(MIN_GAP, gap)), maxDepth };
        }
        maxDepth -= 1;
    }
}

/**
 * Which heading the reader is currently in: the last one whose top has passed
 * the band at the top of the scrollport. Bottomed-out scroll always reports the
 * last heading, so the final (often short) section can still light up.
 */
export function pickActiveIndex(headings: OutlineHeading[], scroller: HTMLElement | null): number {
    if (headings.length === 0 || !scroller) {
        return 0;
    }
    if (scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 1) {
        return headings.length - 1;
    }
    const top = scroller.getBoundingClientRect().top;
    let active = 0;
    for (let i = 0; i < headings.length; i += 1) {
        if (headings[i].el.getBoundingClientRect().top - top <= ACTIVE_BAND) {
            active = i;
        } else {
            break;
        }
    }
    return active;
}

/** Gap left above a heading after jumping to it (matches `scroll-margin-top`
 *  in markdown.css, which covers the `#anchor` path). */
const HEADING_LANDING_OFFSET = 16;

/** Forgiveness around the rail's own box before the outline opens. Aiming at a
 *  thin column is easy left-to-right and fiddly at its two ends, hence the
 *  taller vertical allowance. */
const RAIL_HOVER_PADDING_X = 6;
const RAIL_HOVER_PADDING_Y = 20;

/**
 * Is the pointer on (or just beside) the rail?
 *
 * Derived from the rail's real geometry rather than a fixed band along the
 * panel edge: a band wide enough to be comfortable also fires well before the
 * pointer reaches the ticks, and one spanning the panel's full height fires
 * when merely reaching for the toolbar or the ends of the scrollbar. Reading
 * the box back also keeps the target honest when tick lengths change.
 *
 * Unbounded to the right: past the rail there is only the panel edge and the
 * scrollbar, so there is nothing there to exclude.
 */
export function isPointerNearRail(rail: HTMLElement | null, x: number, y: number): boolean {
    if (!rail) {
        return false;
    }
    const box = rail.getBoundingClientRect();
    return (
        x >= box.left - RAIL_HOVER_PADDING_X &&
        y >= box.top - RAIL_HOVER_PADDING_Y &&
        y <= box.bottom + RAIL_HOVER_PADDING_Y
    );
}

/**
 * Scroll a heading to the top of its container.
 *
 * Two deliberate departures from the `#anchor` handler in Markdown.tsx:
 * we never resolve the id back to an element (the outline already holds the
 * node, and re-looking it up would mean guessing whether the id needs
 * decoding — a heading id may legitimately contain `%`), and we scroll the
 * container itself rather than calling `scrollIntoView`, which would also
 * scroll every scrollable ancestor and drag the chat column behind the panel.
 */
export function scrollHeadingIntoView(
    el: HTMLElement | undefined,
    scroller: HTMLElement | null,
): void {
    if (!el) {
        return;
    }
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    const behavior: ScrollBehavior = reduced ? 'auto' : 'smooth';
    if (!scroller) {
        el.scrollIntoView({ behavior, block: 'start' });
        return;
    }
    const offset = el.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
    const top = Math.max(0, scroller.scrollTop + offset - HEADING_LANDING_OFFSET);
    scroller.scrollTo({ top, behavior });
}
