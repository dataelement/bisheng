/* eslint-disable no-restricted-syntax -- fixtures are Chinese document text being matched, not UI copy */
import {
    buildLocateAnchors,
    clearCitedHighlight,
    findCitedSpan,
    highlightCitedText,
    normalizeForLocate,
} from './citationLocate';

describe('normalizeForLocate', () => {
    it('keeps letters, digits and CJK; folds case and full-width', () => {
        expect(normalizeForLocate('第二条 适用范围：ＯＫＲ 2025！')).toBe('第二条适用范围okr2025');
    });
});

describe('buildLocateAnchors', () => {
    it('drops markdown markers and auto-numbering', () => {
        const anchors = buildLocateAnchors('## 第一章 总则\n1. 为建立科学、透明、高效的绩效管理体系\n- 推动公司战略目标落地和执行');
        // The heading is shorter than an anchor and is dropped; the list lines lose their markers.
        expect(anchors).toEqual(['为建立科学透明高效的绩效管理体系', '推动公司战略目标落地和执行']);
    });

    it('falls back to the whole chunk when every sentence is short', () => {
        expect(buildLocateAnchors('版本号 V1.0')).toEqual(['版本号v10']);
    });

    it('unwraps the paragraph_content tag', () => {
        expect(buildLocateAnchors('<paragraph_content>本规则适用于公司全体正式员工</paragraph_content>')).toEqual([
            '本规则适用于公司全体正式员工',
        ]);
    });
});

describe('findCitedSpan', () => {
    const doc = normalizeForLocate(
        '第一章 总则 第一条 目的 为建立科学透明高效的绩效管理体系，推动公司战略目标落地。' +
            '第二条 适用范围 本规则适用于公司全体正式员工，包括公司高管团队、产品研发团队。' +
            '第三条 基本原则 透明公开、挑战导向、聚焦重点、结果量化、持续反馈。',
    );

    it('locates a chunk whose markup differs from the rendered text', () => {
        const chunk = '### 第二条 适用范围\n本规则适用于公司全体正式员工，包括公司高管团队、产品研发团队。';
        const span = findCitedSpan(doc, chunk);
        expect(span).not.toBeNull();
        expect(doc.slice(span!.start, span!.end)).toContain('本规则适用于公司全体正式员工');
        expect(doc.slice(span!.start, span!.end)).not.toContain('透明公开');
    });

    it('tolerates one anchor that does not match', () => {
        const chunk = '本规则适用于公司全体正式员工。| 这一行表格被转换器改写过了完全对不上 |\n包括公司高管团队、产品研发团队。';
        expect(findCitedSpan(doc, chunk)).not.toBeNull();
    });

    it('returns null when the chunk is not in the file', () => {
        expect(findCitedSpan(doc, '第二十二条 个人奖励：个人季度得分达到零点八以上者额外获得奖励。')).toBeNull();
    });
});

describe('highlightCitedText', () => {
    it('marks the containing blocks across split text nodes', () => {
        document.body.innerHTML = `<div id="root">
            <h2>第二条 适用范围</h2>
            <p>本规则适用于<strong>公司全体正式员工</strong>，包括公司高管团队、产品研发团队。</p>
            <p>第三条 基本原则 透明公开、挑战导向、聚焦重点、结果量化、持续反馈。</p>
        </div>`;
        const root = document.getElementById('root')!;
        Element.prototype.scrollIntoView = jest.fn();
        const found = highlightCitedText(root, ['本规则适用于公司全体正式员工，包括公司高管团队、产品研发团队。']);
        expect(found).toBe(true);
        const hits = root.querySelectorAll('[data-cite-hit]');
        expect(hits).toHaveLength(1);
        expect(hits[0].tagName).toBe('P');
        expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    });

    it('reports a miss and leaves no marks', () => {
        document.body.innerHTML = '<div id="root"><p>完全无关的正文内容在这里出现</p></div>';
        const root = document.getElementById('root')!;
        expect(highlightCitedText(root, ['第二十二条 个人奖励：个人季度得分达到零点八以上者'])).toBe(false);
        expect(root.querySelectorAll('[data-cite-hit]')).toHaveLength(0);
    });

    it('draws one continuous band per passage and clears it', () => {
        document.body.innerHTML = `<div id="root">
            <p>第一条 目的 为建立科学、透明、高效的绩效管理体系，推动公司战略目标落地。</p>
            <p>第二条 适用范围 本规则适用于公司全体正式员工，包括高管团队与研发团队。</p>
            <p>第三条 基本原则 透明公开、挑战导向、聚焦重点、结果量化、持续反馈。</p>
        </div>`;
        const root = document.getElementById('root')!;
        Element.prototype.scrollIntoView = jest.fn();
        const chunk = '第一条 目的 为建立科学、透明、高效的绩效管理体系，推动公司战略目标落地。\n第二条 适用范围 本规则适用于公司全体正式员工，包括高管团队与研发团队。';
        expect(highlightCitedText(root, [chunk])).toBe(true);
        // two paragraphs, one band: the passage reads as one quotation
        expect(root.querySelectorAll('[data-cite-hit]')).toHaveLength(2);
        expect(root.querySelectorAll('[data-cite-band]')).toHaveLength(1);
        // re-locating (next occurrence) never stacks bands
        highlightCitedText(root, [chunk]);
        expect(root.querySelectorAll('[data-cite-band]')).toHaveLength(1);
        clearCitedHighlight(root);
        expect(root.querySelectorAll('[data-cite-band]')).toHaveLength(0);
        expect(root.querySelectorAll('[data-cite-hit]')).toHaveLength(0);
        expect(root.style.position).toBe('');
    });
});
