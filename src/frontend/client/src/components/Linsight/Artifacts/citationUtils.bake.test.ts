/**
 * F069 P2 (AC-20 / AC-22 / AC-24): baking private-use citation spans into
 * visible `[n]` markers plus a reference list for the client-side "save as
 * markdown" path. Pure-function tests; the fetch path lives in
 * artifactUtils.test.ts.
 */
import type { ChatCitation } from '~/api/chatApi';
import {
    bakeCitationsForExport,
    stripCitationHandles,
    stripCitationMarkers,
} from '~/components/Chat/Messages/Content/citationUtils';

// citationUtils reads the line labels through i18next.t; render the keys with
// their positional argument so the fixtures stay ASCII and the assertions
// prove the argument is threaded.
jest.mock('i18next', () => ({
    __esModule: true,
    default: {
        t: (key: string, options?: Record<string, unknown>) =>
            options && '0' in options ? `${key}:${String(options[0])}` : key,
    },
}));

const HEADING = 'References';
const S = '';
const SEP = '';
const E = '';

const ragDetail = (citationId: string, over: Partial<ChatCitation['sourcePayload']> = {}): ChatCitation => ({
    citationId,
    type: 'knowledgeSearch',
    sourcePayload: {
        documentName: 'policy.pdf',
        knowledgeName: 'Policies',
        items: [
            { itemId: '0', chunkId: 'c0', page: 3 },
            { itemId: '1', chunkId: 'c1', chunkIndex: 7 },
        ],
        ...over,
    },
});

const webDetail = (citationId: string, over: Partial<ChatCitation['sourcePayload']> = {}): ChatCitation => ({
    citationId,
    type: 'webSearch',
    sourcePayload: {
        title: 'Example page',
        source: 'example.com',
        url: 'https://example.com/a',
        items: [{ itemId: '3' }],
        ...over,
    },
});

const articleDetail = (citationId: string): ChatCitation => ({
    citationId,
    type: 'articleSearch',
    sourcePayload: { title: 'Weekly brief', sourceUrl: 'https://news.example/1', items: [{ itemId: '5' }] },
});

const details = {
    knowledgesearch_aaa: ragDetail('knowledgesearch_aaa'),
    websearch_bbb: webDetail('websearch_bbb'),
    articlesearch_ccc: articleDetail('articlesearch_ccc'),
};

describe('bakeCitationsForExport grammar', () => {
    it('bakes a single span into [1] and appends the reference list', () => {
        const text = `Claim A${S}knowledgesearch_aaa:0${E}.`;
        expect(bakeCitationsForExport(text, details, HEADING)).toBe(
            'Claim A[1].\n\n## References\n\n' +
            '1. 《policy.pdf》 · com_linsight_export_page:3 · Policies\n',
        );
    });

    it('numbers by first appearance across spans and renders a multi-ref span as [1][2]', () => {
        const text =
            `A${S}websearch_bbb:3${E} then B${S}knowledgesearch_aaa:0${SEP}websearch_bbb:3${E}.`;
        const baked = bakeCitationsForExport(text, details, HEADING);
        expect(baked.startsWith('A[1] then B[2][1].\n\n## References\n\n')).toBe(true);
        expect(baked).toContain('1. Example page · example.com · https://example.com/a\n');
        expect(baked).toContain('2. 《policy.pdf》 · com_linsight_export_page:3 · Policies\n');
    });

    it('dedupes the same chunk to one number and different chunks of one document to two', () => {
        const text =
            `A${S}knowledgesearch_aaa:0${E} B${S}knowledgesearch_aaa:0${E} ` +
            `C${S}knowledgesearch_aaa:1${E} D${S}knowledgesearch_aaa:0${SEP}knowledgesearch_aaa:0${E}`;
        const baked = bakeCitationsForExport(text, details, HEADING);
        expect(baked.startsWith('A[1] B[1] C[2] D[1]\n\n## References\n\n')).toBe(true);
        // The second chunk has no page, so it falls back to its chunk index.
        expect(baked).toContain('2. 《policy.pdf》 · com_linsight_export_chunk:7 · Policies\n');
        expect(baked.split('\n').filter((line) => /^\d+\. /.test(line))).toHaveLength(2);
    });

    it('removes a span whose refs have no detail, and keeps only resolved refs in a mixed span', () => {
        const text =
            `A${S}knowledgesearch_zzz:0${E} B${S}knowledgesearch_zzz:0${SEP}websearch_bbb:3${E}.`;
        expect(bakeCitationsForExport(text, details, HEADING)).toBe(
            'A B[1].\n\n## References\n\n1. Example page · example.com · https://example.com/a\n',
        );
    });

    it('drops unknown short handles [S99] alongside baking (AC-19)', () => {
        const text = `A${S}knowledgesearch_aaa:0${E} [S99] B [S3][S7].`;
        expect(bakeCitationsForExport(text, details, HEADING).startsWith('A[1]  B .\n\n## References')).toBe(true);
    });

    it('leaves code fences and inline code untouched', () => {
        const fence = '```\n' + `${S}knowledgesearch_aaa:0${E} [S3]\n` + '```';
        const inline = '`' + `${S}websearch_bbb:3${E}` + '`';
        const text = `Before${S}knowledgesearch_aaa:0${E}\n${fence}\n${inline} after.`;
        const baked = bakeCitationsForExport(text, details, HEADING);
        expect(baked).toContain(fence);
        expect(baked).toContain(inline);
        expect(baked.startsWith('Before[1]\n')).toBe(true);
        // Only the prose span was numbered; the fenced one is not on the list.
        expect(baked.split('\n').filter((line) => /^\d+\. /.test(line))).toHaveLength(1);
    });

    it('renders an article line as title and source url', () => {
        const text = `A${S}articlesearch_ccc:5${E}`;
        expect(bakeCitationsForExport(text, details, HEADING)).toBe(
            'A[1]\n\n## References\n\n1. Weekly brief · https://news.example/1\n',
        );
    });

    it('lets a web title fall back to the url without printing the url twice', () => {
        const local = { websearch_ddd: webDetail('websearch_ddd', { title: '', source: '' }) };
        const text = `A${S}websearch_ddd:3${E}`;
        expect(bakeCitationsForExport(text, local, HEADING)).toBe(
            'A[1]\n\n## References\n\n1. https://example.com/a\n',
        );
    });

    it('omits the location when neither page nor chunk index is known', () => {
        const local = {
            knowledgesearch_eee: ragDetail('knowledgesearch_eee', {
                knowledgeName: undefined,
                items: [{ itemId: '0' }],
            }),
        };
        const text = `A${S}knowledgesearch_eee:0${E}`;
        expect(bakeCitationsForExport(text, local, HEADING)).toBe(
            'A[1]\n\n## References\n\n1. 《policy.pdf》\n',
        );
    });

    it('adds no section and strips every marker when nothing resolves', () => {
        const text = `A${S}knowledgesearch_zzz:0${E} B ${SEP} C [S4].`;
        const baked = bakeCitationsForExport(text, {}, HEADING);
        expect(baked).toBe('A B  C .');
        expect(baked).not.toMatch(/[]/);
        expect(baked).not.toContain('## References');
    });

    it('matches the P1 strip when nothing resolves (same bytes as the fallback path)', () => {
        const text = `A${S}knowledgesearch_zzz:0${E} B [S4] ` + '`[S5]`' + ' [S6](u)';
        expect(bakeCitationsForExport(text, {}, HEADING)).toBe(stripCitationHandles(stripCitationMarkers(text)));
    });

    it('is idempotent on already-baked text', () => {
        const once = bakeCitationsForExport(`A${S}knowledgesearch_aaa:0${E} B [S9].`, details, HEADING);
        expect(bakeCitationsForExport(once, details, HEADING)).toBe(once);
    });

    it('normalises the escaped marker form before baking', () => {
        const text = 'A\\ue200knowledgesearch_aaa:0\\ue202.';
        expect(bakeCitationsForExport(text, details, HEADING).startsWith('A[1].\n\n## References')).toBe(true);
    });

    it('never leaves an internal id or a marker in the output (AC-24)', () => {
        const text = `A${S}knowledgesearch_aaa:0${SEP}websearch_zzz:1${E} ${S} orphan`;
        const baked = bakeCitationsForExport(text, details, HEADING);
        expect(baked).not.toContain('knowledgesearch_');
        expect(baked).not.toContain('websearch_');
        expect(baked).not.toMatch(/[]/);
    });

    it('returns empty input as is', () => {
        expect(bakeCitationsForExport('', details, HEADING)).toBe('');
    });
});
