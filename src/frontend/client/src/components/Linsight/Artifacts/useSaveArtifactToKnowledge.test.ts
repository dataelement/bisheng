import request from '~/api/request';
import { fetchArtifactBlob } from './artifactUtils';
import { resolveUniqueFileName } from './useSaveArtifactToKnowledge';

jest.mock('~/api/request', () => ({
    __esModule: true,
    default: { post: jest.fn() },
}));

/**
 * The spec wants a same-layer collision to land as `name(N).ext` with the source
 * deliverable untouched. The backend can't do that for us — its dedup marks the
 * upload FAILED and offers an overwrite that rewrites the PRE-EXISTING row —
 * so the free name is resolved here, before staging.
 */
describe('resolveUniqueFileName', () => {
    it('keeps the original name when nothing collides', () => {
        expect(resolveUniqueFileName(new Set(), 'report.md')).toBe('report.md');
        expect(resolveUniqueFileName(new Set(['other.md']), 'report.md')).toBe('report.md');
    });

    it('appends (1) on the first collision', () => {
        expect(resolveUniqueFileName(new Set(['report.md']), 'report.md')).toBe('report(1).md');
    });

    it('skips suffixes that are themselves taken', () => {
        const taken = new Set(['report.md', 'report(1).md', 'report(2).md']);
        expect(resolveUniqueFileName(taken, 'report.md')).toBe('report(3).md');
    });

    it('suffixes before the last dot only', () => {
        expect(resolveUniqueFileName(new Set(['a.b.md']), 'a.b.md')).toBe('a.b(1).md');
    });

    it('handles an extensionless name and a dotfile', () => {
        expect(resolveUniqueFileName(new Set(['README']), 'README')).toBe('README(1)');
        expect(resolveUniqueFileName(new Set(['.gitignore']), '.gitignore')).toBe('.gitignore(1)');
    });

    it('falls back to a unique suffix instead of looping past maxAttempts', () => {
        const taken = new Set(['x.md', 'x(1).md', 'x(2).md', 'x(3).md']);
        const resolved = resolveUniqueFileName(taken, 'x.md', 3);
        expect(taken.has(resolved)).toBe(false);
        expect(resolved).toMatch(/^x\(\d+\)\.md$/);
    });
});

/**
 * A user-uploaded non-image source is persisted as its PARSED MARKDOWN, so the
 * bytes are markdown whatever the display name says. Both the local download and
 * the knowledge-space save read the name through here so they can't disagree.
 */
describe('fetchArtifactBlob naming', () => {
    const mockFetch = (body: string, type: string) => {
        global.fetch = jest.fn().mockResolvedValue({
            ok: true,
            blob: async () => new Blob([body], { type }),
        }) as unknown as typeof fetch;
    };

    beforeEach(() => {
        (request.post as jest.Mock).mockResolvedValue({
            status_code: 200,
            data: { file_path: '/presigned/x' },
        });
        mockFetch('# hi', 'text/markdown');
    });

    it('rewrites an uploaded source to .md', async () => {
        const { fileName } = await fetchArtifactBlob(
            { file_id: '1', file_name: 'report.pdf', file_url: 'uploads/report/index.md', source: 'upload' },
            'SV-1',
        );
        expect(fileName).toBe('report.md');
    });

    it('keeps the real name for a generated output and for an image upload', async () => {
        const output = await fetchArtifactBlob(
            { file_id: '1', file_name: 'report.html', file_url: 'output/report.html', source: 'output' },
            'SV-1',
        );
        expect(output.fileName).toBe('report.html');

        const image = await fetchArtifactBlob(
            {
                file_id: '2', file_name: 'chart.png', file_url: 'uploads/chart.png',
                source: 'upload', previewAsImage: true,
            },
            'SV-1',
        );
        expect(image.fileName).toBe('chart.png');
    });

    // The download wrapper prepends a UTF-8 BOM to CSV so Excel picks the right
    // encoding; that must not reach a file entering knowledge-base parsing.
    it('returns CSV bytes without a BOM', async () => {
        mockFetch('a,b', 'text/csv');

        const { blob } = await fetchArtifactBlob(
            { file_id: '3', file_name: 'data.csv', file_url: 'output/data.csv', source: 'output' },
            'SV-1',
        );

        expect(await blob.text()).toBe('a,b');
    });
});
