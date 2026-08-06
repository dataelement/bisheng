import {
    type OutlineHeading,
    collectHeadings,
    getScrollParent,
    headingsEqual,
    normalizeLevels,
    pickActiveIndex,
    scrollHeadingIntoView,
    solveRailLayout,
} from './markdownOutlineUtils';

describe('normalizeLevels', () => {
    it('maps the shallowest level present to depth 1', () => {
        // A report that starts at `##` must not have its whole staircase shifted.
        const out = normalizeLevels([{ level: 2 }, { level: 3 }, { level: 2 }]);
        expect(out.map((h) => h.depth)).toEqual([1, 2, 1]);
    });

    it('keeps h1-rooted documents unchanged', () => {
        const out = normalizeLevels([{ level: 1 }, { level: 2 }, { level: 3 }]);
        expect(out.map((h) => h.depth)).toEqual([1, 2, 3]);
    });

    it('preserves gaps when a level is skipped', () => {
        const out = normalizeLevels([{ level: 2 }, { level: 4 }]);
        expect(out.map((h) => h.depth)).toEqual([1, 3]);
    });

    it('gives every heading depth 1 when they are all the same level', () => {
        const out = normalizeLevels([{ level: 3 }, { level: 3 }]);
        expect(out.map((h) => h.depth)).toEqual([1, 1]);
    });

    it('returns an empty list for no headings', () => {
        expect(normalizeLevels([])).toEqual([]);
    });
});

describe('solveRailLayout', () => {
    it('uses the roomy gap when the ticks fit easily', () => {
        expect(solveRailLayout([1, 2, 2, 3], 600)).toEqual({ gap: 6, maxDepth: 3 });
    });

    it('tightens the gap before dropping any level', () => {
        // 60 ticks into 304px of usable height: the roomy 6px gap would overflow,
        // but ~3px fits — so every level survives.
        const depths = Array.from({ length: 60 }, (_, i) => (i % 3) + 1);
        const { gap, maxDepth } = solveRailLayout(depths, 400);
        expect(maxDepth).toBe(3);
        expect(gap).toBeGreaterThanOrEqual(2);
        expect(gap).toBeLessThan(6);
    });

    it('drops the deepest level once even the minimum gap overflows', () => {
        const depths = Array.from({ length: 300 }, (_, i) => (i % 3) + 1);
        expect(solveRailLayout(depths, 500).maxDepth).toBeLessThan(3);
    });

    it('never drops below depth 2, however dense the document is', () => {
        const depths = Array.from({ length: 4000 }, () => 1);
        expect(solveRailLayout(depths, 400).maxDepth).toBe(1);
        const mixed = Array.from({ length: 4000 }, (_, i) => (i % 2) + 1);
        expect(solveRailLayout(mixed, 400).maxDepth).toBe(2);
    });

    it('falls back to the roomy gap before the container has been measured', () => {
        expect(solveRailLayout([1, 2, 3], 0)).toEqual({ gap: 6, maxDepth: 3 });
    });
});

/** Fake heading whose rect sits `top` px below the scroller's own top. */
const mkHeading = (index: number, top: number): OutlineHeading => ({
    id: `h${index}`,
    text: `Heading ${index}`,
    level: 1,
    depth: 1,
    index,
    el: { getBoundingClientRect: () => ({ top }) } as unknown as HTMLElement,
});

const mkScroller = (over: Partial<HTMLElement> = {}) =>
    ({
        scrollTop: 0,
        clientHeight: 500,
        scrollHeight: 2000,
        getBoundingClientRect: () => ({ top: 0 }),
        ...over,
    }) as unknown as HTMLElement;

describe('pickActiveIndex', () => {
    it('reports the first heading at the top of the document', () => {
        const headings = [mkHeading(0, 10), mkHeading(1, 400), mkHeading(2, 900)];
        expect(pickActiveIndex(headings, mkScroller())).toBe(0);
    });

    it('reports the last heading whose top has passed the band', () => {
        const headings = [mkHeading(0, -600), mkHeading(1, -100), mkHeading(2, 300)];
        expect(pickActiveIndex(headings, mkScroller({ scrollTop: 700 }))).toBe(1);
    });

    it('keeps the previous heading while the next one is still below the band', () => {
        // 25px is one pixel past the 24px band — not current yet.
        const headings = [mkHeading(0, -50), mkHeading(1, 25)];
        expect(pickActiveIndex(headings, mkScroller({ scrollTop: 100 }))).toBe(0);
    });

    it('lights up the final heading once scrolled to the bottom', () => {
        const headings = [mkHeading(0, -900), mkHeading(1, -300), mkHeading(2, 480)];
        const scroller = mkScroller({ scrollTop: 1500, clientHeight: 500, scrollHeight: 2000 });
        expect(pickActiveIndex(headings, scroller)).toBe(2);
    });

    it('is safe with no headings or no scroller', () => {
        expect(pickActiveIndex([], mkScroller())).toBe(0);
        expect(pickActiveIndex([mkHeading(0, 0)], null)).toBe(0);
    });
});

describe('collectHeadings', () => {
    const render = (html: string) => {
        const root = document.createElement('div');
        root.innerHTML = html;
        return root;
    };

    it('reads id, text and normalized depth in document order', () => {
        const root = render(`
            <h2 id="a">一、项目概述</h2>
            <p>正文</p>
            <h3 id="b">1.1 项目背景</h3>
            <h2 id="c">二、技术要求</h2>
        `);
        expect(collectHeadings(root)).toMatchObject([
            { id: 'a', text: '一、项目概述', depth: 1, index: 0 },
            { id: 'b', text: '1.1 项目背景', depth: 2, index: 1 },
            { id: 'c', text: '二、技术要求', depth: 1, index: 2 },
        ]);
    });

    it('skips headings with no id or no text, and reindexes what remains', () => {
        const root = render('<h1 id="a">A</h1><h1>no id</h1><h1 id="c">  </h1><h1 id="d">D</h1>');
        expect(collectHeadings(root).map((h) => [h.id, h.index])).toEqual([
            ['a', 0],
            ['d', 1],
        ]);
    });

    it('returns nothing for a null root or a document without headings', () => {
        expect(collectHeadings(null)).toEqual([]);
        expect(collectHeadings(render('<p>just prose</p>'))).toEqual([]);
    });
});

describe('headingsEqual', () => {
    const render = (html: string) => {
        const root = document.createElement('div');
        root.innerHTML = html;
        return collectHeadings(root);
    };

    it('treats a re-scan of unchanged markup as equal', () => {
        const html = '<h1 id="a">A</h1><h2 id="b">B</h2>';
        expect(headingsEqual(render(html), render(html))).toBe(true);
    });

    it('notices an added, renamed or re-levelled heading', () => {
        const base = render('<h1 id="a">A</h1><h2 id="b">B</h2>');
        expect(headingsEqual(base, render('<h1 id="a">A</h1><h2 id="b">B</h2><h2 id="c">C</h2>'))).toBe(false);
        expect(headingsEqual(base, render('<h1 id="a">A</h1><h2 id="b">B2</h2>'))).toBe(false);
        expect(headingsEqual(base, render('<h1 id="a">A</h1><h3 id="b">B</h3>'))).toBe(false);
    });
});

describe('scrollHeadingIntoView', () => {
    const mkPair = (headingTop: number, scrollTop: number) => {
        const scrollTo = jest.fn();
        const scroller = {
            scrollTop,
            scrollTo,
            getBoundingClientRect: () => ({ top: 100 }),
        } as unknown as HTMLElement;
        const el = {
            getBoundingClientRect: () => ({ top: headingTop }),
            scrollIntoView: jest.fn(),
        } as unknown as HTMLElement;
        return { el, scroller, scrollTo };
    };

    it('scrolls the container to the heading, minus the landing offset', () => {
        // Heading sits 500px below the scrollport top, which is already at 300.
        const { el, scroller, scrollTo } = mkPair(600, 300);
        scrollHeadingIntoView(el, scroller);
        expect(scrollTo).toHaveBeenCalledWith({ top: 300 + 500 - 16, behavior: 'smooth' });
    });

    it('clamps to the top of the document instead of scrolling negative', () => {
        const { el, scroller, scrollTo } = mkPair(105, 0);
        scrollHeadingIntoView(el, scroller);
        expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' });
    });

    it('honours prefers-reduced-motion', () => {
        // jsdom ships no matchMedia at all — which is also the "not reduced"
        // path the other cases above exercise.
        const original = window.matchMedia;
        window.matchMedia = (() => ({ matches: true })) as unknown as typeof window.matchMedia;
        const { el, scroller, scrollTo } = mkPair(600, 0);
        scrollHeadingIntoView(el, scroller);
        expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'auto' }));
        window.matchMedia = original;
    });

    it('falls back to scrollIntoView when no container was found', () => {
        const { el } = mkPair(600, 0);
        scrollHeadingIntoView(el, null);
        expect(el.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
    });

    it('does nothing without a heading', () => {
        const { scroller, scrollTo } = mkPair(600, 0);
        scrollHeadingIntoView(undefined, scroller);
        expect(scrollTo).not.toHaveBeenCalled();
    });
});

describe('getScrollParent', () => {
    it('walks up to the nearest scrollable ancestor', () => {
        const scroller = document.createElement('div');
        scroller.style.overflowY = 'auto';
        const middle = document.createElement('div');
        const content = document.createElement('div');
        scroller.appendChild(middle);
        middle.appendChild(content);
        document.body.appendChild(scroller);

        expect(getScrollParent(content)).toBe(scroller);
        document.body.removeChild(scroller);
    });

    it('returns null when nothing up the chain scrolls', () => {
        const content = document.createElement('div');
        document.body.appendChild(content);
        expect(getScrollParent(content)).toBeNull();
        document.body.removeChild(content);
    });
});
