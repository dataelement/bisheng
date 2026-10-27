import request from '~/api/request';
import { getArtifactPreviewKind, getPreviewKind } from './artifactUtils';
import { POLL_INTERVAL_MS, POLL_TIMEOUT_MS, pollSlidesPreview } from './useSlidesPreview';

jest.mock('~/api/request', () => ({
    __esModule: true,
    default: { post: jest.fn() },
}));

const mockedRequest = request as jest.Mocked<typeof request>;

type GlobalWithEnv = typeof globalThis & { __APP_ENV__: Record<string, unknown> };
const appEnvHost = globalThis as GlobalWithEnv;

describe('F111 slides preview kind', () => {
    it('routes task-generated ppt/pptx to the slides kind', () => {
        expect(getPreviewKind('annual report.pptx')).toBe('slides');
        expect(getPreviewKind('old.PPT')).toBe('slides');
        expect(getPreviewKind('report.pdf')).toBe('document');
        expect(getPreviewKind('legacy.doc')).toBe('unsupported');
    });

    it('keeps uploaded decks on their parsed-markdown preview', () => {
        expect(
            getArtifactPreviewKind({ file_name: 'deck.pptx', file_url: 'u', source: 'upload' } as never),
        ).toBe('markdown');
    });
});

describe('F111 pollSlidesPreview', () => {
    const origEnv = appEnvHost.__APP_ENV__;

    beforeEach(() => {
        jest.useFakeTimers();
        mockedRequest.post.mockReset();
        appEnvHost.__APP_ENV__ = { ...origEnv, BASE_URL: '/workspace' };
    });

    afterEach(() => {
        jest.useRealTimers();
        appEnvHost.__APP_ENV__ = origEnv;
    });

    it('posts to file_preview with the share token and returns the prefixed PDF url', async () => {
        mockedRequest.post.mockResolvedValue({ data: { status: 'ready', file_path: '/bisheng/p.pdf?s=1' } } as never);
        const url = await pollSlidesPreview('linsight/final_result/v/a.pptx', 'v', () => false, 'tok-1');
        expect(url).toBe('/workspace/bisheng/p.pdf?s=1');
        const [path, body, config] = mockedRequest.post.mock.calls[0] as [
            string,
            unknown,
            { headers: Record<string, string> },
        ];
        expect(path).toBe('/api/v1/linsight/workbench/file_preview');
        expect(body).toEqual({ file_url: 'linsight/final_result/v/a.pptx', session_version_id: 'v' });
        expect(config.headers['share-token']).toBe('tok-1');
    });

    it('polls while converting, then returns once ready', async () => {
        mockedRequest.post
            .mockResolvedValueOnce({ data: { status: 'converting' } } as never)
            .mockResolvedValueOnce({ data: { status: 'ready', file_path: '/x.pdf' } } as never);
        const pending = pollSlidesPreview('k', 'v', () => false, '');
        await jest.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        await expect(pending).resolves.toBe('/workspace/x.pdf');
        expect(mockedRequest.post).toHaveBeenCalledTimes(2);
    });

    it('gives up after the timeout while the backend keeps converting', async () => {
        mockedRequest.post.mockResolvedValue({ data: { status: 'converting' } } as never);
        let clock = 0;
        const pending = pollSlidesPreview('k', 'v', () => false, '', () => clock);
        for (let i = 0; i < POLL_TIMEOUT_MS / POLL_INTERVAL_MS + 2; i += 1) {
            clock += POLL_INTERVAL_MS;
            await jest.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        }
        await expect(pending).resolves.toBeNull();
    });

    it('propagates request errors so the caller can show the failure fallback', async () => {
        mockedRequest.post.mockRejectedValue(new Error('11025'));
        await expect(pollSlidesPreview('k', 'v', () => false, '')).rejects.toThrow('11025');
    });
});
