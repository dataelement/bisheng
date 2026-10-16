/**
 * F071: locate a cited chunk inside a rendered non-PDF source (docx / md / txt).
 *
 * The chunk text and the rendered preview come from the same file but through
 * different converters: knowledge ingestion turns a docx into markdown with
 * pandoc, while the preview renders the docx to HTML with mammoth. They agree on
 * the words and disagree on the markup (`#`, `|`, list numbers, line breaks), so
 * both sides are reduced to letters / digits / CJK only, and the chunk is matched
 * by several sentence anchors rather than as one string — one table row that
 * pandoc wrapped differently must not sink the whole match.
 */

import type { ChatCitation } from '~/api/chatApi';

/** Resolve the clicked historical item, never a different chunk as fallback. */
export function getCitedPassageChunks(detail: ChatCitation | null, itemId?: string): string[] {
    const items = detail?.sourcePayload?.items ?? [];
    const targetId = itemId || detail?.itemId;
    const item = targetId
        ? items.find((candidate) => candidate.itemId === targetId || candidate.chunkId === targetId)
        : items[0];
    const text = item?.content?.trim() || item?.snippet?.trim();
    return text ? [text] : [];
}

/** Characters kept for matching: letters, digits and CJK ideographs. */
const KEEP_RE = /[\p{L}\p{N}]/u;
/** Anchors shorter than this match too easily to mean anything. */
const MIN_ANCHOR = 8;
/** Long anchors are matched by prefix, so one differing tail char doesn't miss. */
const ANCHOR_PREFIX = 24;

function foldChar(ch: string): string {
    const code = ch.charCodeAt(0);
    // Full-width ASCII variants (Ａ-ｚ, ０-９) → half-width.
    if (code >= 0xff01 && code <= 0xff5e) {
        return String.fromCharCode(code - 0xfee0).toLowerCase();
    }
    return ch.toLowerCase();
}

/** Reduce text to the comparable character stream. */
export function normalizeForLocate(text: string): string {
    let out = '';
    for (const ch of text) {
        const folded = foldChar(ch);
        if (KEEP_RE.test(folded)) out += folded;
    }
    return out;
}

/** Strip the markdown / tag markup ingestion adds, line by line. */
function stripChunkMarkup(chunk: string): string {
    return chunk
        .replace(/<\/?[a-z_][^>]*>/gi, ' ') // <paragraph_content>, inline html
        .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ') // images
        .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1') // links keep their text
        .split('\n')
        .map((line) =>
            line
                .replace(/^\s*#{1,6}\s+/, '') // headings
                .replace(/^\s*(?:[-*+]|\d+[.)、])\s+/, '') // list markers / auto-numbering
                .replace(/^\s*>\s?/, ''), // quotes
        )
        .join('\n');
}

/** Split a chunk into normalized sentence anchors, longest-first is not needed: order is kept. */
export function buildLocateAnchors(chunk: string): string[] {
    const pieces = stripChunkMarkup(chunk).split(/[。！？；!?;\n|]+/);
    const anchors = pieces.map(normalizeForLocate).filter((a) => a.length >= MIN_ANCHOR);
    if (anchors.length) return anchors;
    // A short chunk (a heading, a table cell) is its own single anchor.
    const whole = normalizeForLocate(stripChunkMarkup(chunk));
    return whole.length >= 4 ? [whole] : [];
}

export interface LocatedSpan {
    start: number;
    end: number;
}

function findUniqueSpan(haystack: string, text: string): LocatedSpan | null {
    const at = haystack.indexOf(text);
    return at >= 0 && haystack.indexOf(text, at + 1) < 0
        ? { start: at, end: at + text.length }
        : null;
}

function findAnchor(haystack: string, anchor: string): LocatedSpan | null {
    const exact = findUniqueSpan(haystack, anchor);
    if (exact) return exact;
    if (anchor.length <= ANCHOR_PREFIX) return null;
    const head = anchor.slice(0, ANCHOR_PREFIX);
    const prefix = findUniqueSpan(haystack, head);
    if (prefix) return prefix;
    const tail = anchor.slice(-ANCHOR_PREFIX);
    return findUniqueSpan(haystack, tail);
}

/**
 * Find where `chunk` sits inside the already-normalized `haystack`.
 * Returns null when too few anchors hit to trust the result — the caller then
 * shows the "couldn't find it" hint instead of highlighting a wrong place.
 */
export function findCitedSpan(haystack: string, chunk: string): LocatedSpan | null {
    const anchors = buildLocateAnchors(chunk);
    if (!anchors.length || !haystack) return null;

    const whole = normalizeForLocate(stripChunkMarkup(chunk));
    if (haystack.includes(whole)) {
        // Prefer the complete quote; identical quotes cannot be disambiguated
        // from text alone, so show the quote instead of guessing a position.
        return findUniqueSpan(haystack, whole);
    }

    const hits = anchors.map((a) => findAnchor(haystack, a)).filter((h): h is LocatedSpan => !!h);
    const needed = Math.max(1, Math.ceil(anchors.length * 0.3));
    if (hits.length < needed) return null;

    // Anchors that repeat elsewhere in the file (a boilerplate sentence) can land
    // far away; keep the hits clustered around the median one.
    const chunkLen = anchors.reduce((n, a) => n + a.length, 0);
    const sorted = [...hits].sort((a, b) => a.start - b.start);
    const median = sorted[Math.floor(sorted.length / 2)].start;
    const window = Math.max(chunkLen * 1.5, 200);
    const cluster = sorted.filter((h) => Math.abs(h.start - median) <= window);
    if (cluster.length < needed) return null;

    return {
        start: Math.min(...cluster.map((h) => h.start)),
        end: Math.max(...cluster.map((h) => h.end)),
    };
}

/** Attribute marking the blocks that hold the cited text. */
export const CITE_HIT_ATTR = 'data-cite-hit';
/** The drawn band behind one cited passage. */
export const CITE_BAND_ATTR = 'data-cite-band';
const BLOCK_SELECTOR = 'p,li,td,th,h1,h2,h3,h4,h5,h6,pre,blockquote,dt,dd';
/** Breathing room between the band edge and the text it covers. */
const BAND_PAD_X = 8;
const BAND_PAD_Y = 4;

// Per-root teardown of the drawn bands (observers, restored positions).
const bandTeardown = new WeakMap<HTMLElement, () => void>();

export function clearCitedHighlight(root: HTMLElement) {
    bandTeardown.get(root)?.();
    bandTeardown.delete(root);
    root.querySelectorAll(`[${CITE_BAND_ATTR}]`).forEach((el) => el.remove());
    root.querySelectorAll(`[${CITE_HIT_ATTR}]`).forEach((el) => el.removeAttribute(CITE_HIT_ATTR));
    root.removeAttribute(CITE_HIT_ATTR);
}

function inDocumentOrder(a: Node, b: Node): number {
    return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
}

function commonAncestor(blocks: HTMLElement[], root: HTMLElement): HTMLElement {
    if (blocks.includes(root)) return root;
    let anchor: HTMLElement | null = blocks[0].parentElement;
    while (anchor && anchor !== root && !blocks.every((b) => anchor!.contains(b))) {
        anchor = anchor.parentElement;
    }
    return anchor ?? root;
}

/**
 * Draw one continuous band behind each cited passage.
 *
 * Tinting every paragraph on its own leaves white stripes at the paragraph
 * margins and puts the rule flush against the text; a single band per passage
 * reads as one quotation, keeps a small gutter, and never changes the layout of
 * the document (it is absolutely positioned inside the passage's own container,
 * so it scrolls with it). It is redrawn when the panel is resized.
 */
type Passage = { blocks: HTMLElement[]; range: Range | null };

function drawBands(root: HTMLElement, passages: Passage[]) {
    const drawn: Array<{ anchor: HTMLElement; blocks: HTMLElement[]; range: Range | null; band: HTMLDivElement }> = [];
    const restored: HTMLElement[] = [];
    for (const { blocks, range } of passages) {
        if (!blocks.length) continue;
        const anchor = commonAncestor(blocks, root);
        if (getComputedStyle(anchor).position === 'static') {
            anchor.style.position = 'relative';
            restored.push(anchor);
        }
        const band = document.createElement('div');
        band.setAttribute(CITE_BAND_ATTR, '');
        band.setAttribute('aria-hidden', 'true');
        Object.assign(band.style, {
            position: 'absolute',
            pointerEvents: 'none',
            background: 'rgb(var(--brand-500) / 0.07)',
            borderLeft: '2px solid rgb(var(--brand-500))',
            borderRadius: '2px 6px 6px 2px',
            // The band sits over the text; multiply keeps the text at full contrast.
            mixBlendMode: 'multiply',
        });
        anchor.appendChild(band);
        drawn.push({ anchor, blocks, range, band });
    }

    const layout = () => {
        for (const { anchor, blocks, range, band } of drawn) {
            const box = anchor.getBoundingClientRect();
            const scaleX = anchor.offsetWidth > 0 ? box.width / anchor.offsetWidth : 1;
            const scaleY = anchor.offsetHeight > 0 ? box.height / anchor.offsetHeight : 1;
            // TextViewer renders the entire file in one PRE; use the cited
            // range so a quote near the bottom does not land at the file top.
            const rangeRect = range?.getBoundingClientRect?.();
            const rects = rangeRect?.height ? [rangeRect] : blocks.map((b) => b.getBoundingClientRect());
            const top = Math.min(...rects.map((r) => r.top));
            const bottom = Math.max(...rects.map((r) => r.bottom));
            const left = Math.min(...rects.map((r) => r.left));
            const right = Math.max(...rects.map((r) => r.right));
            Object.assign(band.style, {
                top: `${(top - box.top) / (scaleY || 1) + anchor.scrollTop - BAND_PAD_Y}px`,
                left: `${(left - box.left) / (scaleX || 1) + anchor.scrollLeft - BAND_PAD_X}px`,
                width: `${(right - left) / (scaleX || 1) + BAND_PAD_X * 2}px`,
                height: `${(bottom - top) / (scaleY || 1) + BAND_PAD_Y * 2}px`,
            });
        }
    };
    layout();

    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(layout);
    observer?.observe(root);
    bandTeardown.set(root, () => {
        observer?.disconnect();
        restored.forEach((el) => {
            el.style.position = '';
        });
    });
    return drawn;
}

/**
 * Mark, band and scroll to the passages inside `root` that match `chunks`.
 * Returns true when at least one chunk was located.
 */
export function highlightCitedText(root: HTMLElement, chunks: string[]): boolean {
    clearCitedHighlight(root);

    // Build the normalized stream plus, for every kept char, the text node it came from.
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const owners: Array<{ node: Node; offset: number; length: number }> = [];
    let haystack = '';
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (node.parentElement?.closest('style,script,[aria-hidden="true"]')) continue;
        let offset = 0;
        for (const ch of node.nodeValue || '') {
            const folded = foldChar(ch);
            if (KEEP_RE.test(folded)) {
                haystack += folded;
                for (let index = 0; index < folded.length; index++) {
                    owners.push({ node, offset, length: ch.length });
                }
            }
            offset += ch.length;
        }
    }

    const passages: Passage[] = [];
    for (const chunk of chunks) {
        const span = findCitedSpan(haystack, chunk);
        if (!span) continue;
        const blocks = new Set<HTMLElement>();
        for (let i = span.start; i < span.end; i++) {
            const parent = owners[i]?.node.parentElement;
            const block = (parent?.closest(BLOCK_SELECTOR) as HTMLElement | null) ?? parent;
            if (block && root.contains(block)) blocks.add(block);
        }
        if (blocks.size) {
            const orderedBlocks = [...blocks].sort(inDocumentOrder);
            let range: Range | null = null;
            const start = owners[span.start];
            const end = owners[span.end - 1];
            if (orderedBlocks.length === 1 && orderedBlocks[0].tagName === 'PRE' && start && end) {
                range = document.createRange();
                range.setStart(start.node, start.offset);
                range.setEnd(end.node, end.offset + end.length);
            }
            passages.push({ blocks: orderedBlocks, range });
        }
    }
    if (!passages.length) return false;

    passages.flatMap((p) => p.blocks).forEach((el) => el.setAttribute(CITE_HIT_ATTR, 'true'));
    const bands = drawBands(root, passages);
    const first = passages.map((p) => p.blocks[0]).sort(inDocumentOrder)[0];
    const target = first.tagName === 'PRE'
        ? bands.find((entry) => entry.blocks.includes(first))?.band ?? first
        : first;
    target.scrollIntoView({ block: 'center' });
    return true;
}
