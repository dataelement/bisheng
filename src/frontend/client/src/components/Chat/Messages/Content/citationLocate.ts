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

function findAnchor(haystack: string, anchor: string): LocatedSpan | null {
    let at = haystack.indexOf(anchor);
    if (at >= 0) return { start: at, end: at + anchor.length };
    if (anchor.length <= ANCHOR_PREFIX) return null;
    const head = anchor.slice(0, ANCHOR_PREFIX);
    at = haystack.indexOf(head);
    if (at >= 0) return { start: at, end: at + head.length };
    const tail = anchor.slice(-ANCHOR_PREFIX);
    at = haystack.indexOf(tail);
    if (at >= 0) return { start: at, end: at + tail.length };
    return null;
}

/**
 * Find where `chunk` sits inside the already-normalized `haystack`.
 * Returns null when too few anchors hit to trust the result — the caller then
 * shows the "couldn't find it" hint instead of highlighting a wrong place.
 */
export function findCitedSpan(haystack: string, chunk: string): LocatedSpan | null {
    const anchors = buildLocateAnchors(chunk);
    if (!anchors.length || !haystack) return null;

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
}

function inDocumentOrder(a: Node, b: Node): number {
    return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
}

function commonAncestor(blocks: HTMLElement[], root: HTMLElement): HTMLElement {
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
function drawBands(root: HTMLElement, passages: HTMLElement[][]) {
    const drawn: Array<{ anchor: HTMLElement; blocks: HTMLElement[]; band: HTMLDivElement }> = [];
    const restored: HTMLElement[] = [];
    for (const blocks of passages) {
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
        drawn.push({ anchor, blocks, band });
    }

    const layout = () => {
        for (const { anchor, blocks, band } of drawn) {
            const box = anchor.getBoundingClientRect();
            const rects = blocks.map((b) => b.getBoundingClientRect());
            const top = Math.min(...rects.map((r) => r.top));
            const bottom = Math.max(...rects.map((r) => r.bottom));
            const left = Math.min(...rects.map((r) => r.left));
            const right = Math.max(...rects.map((r) => r.right));
            Object.assign(band.style, {
                top: `${top - box.top + anchor.scrollTop - BAND_PAD_Y}px`,
                left: `${left - box.left + anchor.scrollLeft - BAND_PAD_X}px`,
                width: `${right - left + BAND_PAD_X * 2}px`,
                height: `${bottom - top + BAND_PAD_Y * 2}px`,
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
}

/**
 * Mark, band and scroll to the passages inside `root` that match `chunks`.
 * Returns true when at least one chunk was located.
 */
export function highlightCitedText(root: HTMLElement, chunks: string[]): boolean {
    clearCitedHighlight(root);

    // Build the normalized stream plus, for every kept char, the text node it came from.
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const owners: Node[] = [];
    let haystack = '';
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        for (const ch of node.nodeValue || '') {
            const folded = foldChar(ch);
            if (KEEP_RE.test(folded)) {
                haystack += folded;
                owners.push(node);
            }
        }
    }

    const passages: HTMLElement[][] = [];
    for (const chunk of chunks) {
        const span = findCitedSpan(haystack, chunk);
        if (!span) continue;
        const blocks = new Set<HTMLElement>();
        for (let i = span.start; i < span.end; i++) {
            const parent = owners[i]?.parentElement;
            const block = (parent?.closest(BLOCK_SELECTOR) as HTMLElement | null) ?? parent;
            if (block && root.contains(block)) blocks.add(block);
        }
        if (blocks.size) passages.push([...blocks].sort(inDocumentOrder));
    }
    if (!passages.length) return false;

    passages.flat().forEach((el) => el.setAttribute(CITE_HIT_ATTR, 'true'));
    drawBands(root, passages);
    const first = passages.map((p) => p[0]).sort(inDocumentOrder)[0];
    first.scrollIntoView({ block: 'center' });
    return true;
}
