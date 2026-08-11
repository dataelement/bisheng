import request from '~/api/request';
import { openHtmlArtifactViewer, resolveArtifactUrl } from './artifactUtils';

jest.mock('~/api/request', () => ({
    __esModule: true,
    default: { post: jest.fn() },
}));

const mockedRequest = request as jest.Mocked<typeof request>;

/**
 * Regression: `file_download` was the one linsight endpoint whose client call
 * omitted the `share-token` header. A share recipient (neither owner nor admin)
 * therefore 403'd the moment they previewed or downloaded a task deliverable,
 * and the global 403 handler bounced the whole document to
 * `/c/new?error=11403` — reading as "this share link has no permission".
 */
describe('resolveArtifactUrl share-token plumbing', () => {
    const origEnv = (global as any).__APP_ENV__;

    beforeEach(() => {
        (global as any).__APP_ENV__ = { ...origEnv, BASE_URL: '/workspace' };
        mockedRequest.post.mockResolvedValue({
            status_code: 200,
            data: { file_path: '/tmp-dir/presigned/x.md' },
        } as never);
    });

    afterEach(() => {
        (global as any).__APP_ENV__ = origEnv;
        window.history.pushState({}, '', '/');
    });

    const postArgs = () => mockedRequest.post.mock.calls[0];

    it('sends the share token from the current share route', async () => {
        window.history.pushState({}, '', '/workspace/share/tok-1');

        const url = await resolveArtifactUrl('linsight/final_result/a/report.md', 'SV-1');

        const [path, body, config] = postArgs() as [string, any, any];
        expect(path).toBe('/api/v1/linsight/workbench/file_download');
        expect(body).toEqual({ file_url: 'linsight/final_result/a/report.md', session_version_id: 'SV-1' });
        expect(config.headers['share-token']).toBe('tok-1');
        expect(url).toBe('/workspace/tmp-dir/presigned/x.md');
    });

    // A single unreachable file must not eject the viewer from the page: without
    // this the interceptor does `location.href = /c/new?error=11403`.
    it('opts out of the global 403 redirect', async () => {
        await resolveArtifactUrl('linsight/final_result/a/report.md', 'SV-1');
        expect((postArgs()[2] as any).skip403Redirect).toBe(true);
    });

    it('omits the header off a share route, and keeps Content-Type either way', async () => {
        window.history.pushState({}, '', '/workspace/c/abc');

        await resolveArtifactUrl('linsight/final_result/a/report.md', 'SV-1');

        const config = postArgs()[2] as any;
        expect(config.headers['share-token']).toBeUndefined();
        // _post spreads `config` over its defaults, so a headers key of ours
        // would otherwise drop the default Content-Type.
        expect(config.headers['Content-Type']).toBe('application/json');
    });

    // The /html viewer is a separate tab whose own location is not a share
    // route, so it must forward the token it was opened with.
    it('accepts an explicit token that overrides the route (standalone /html tab)', async () => {
        window.history.pushState({}, '', '/workspace/html');

        await resolveArtifactUrl('linsight/final_result/a/r.html', 'SV-2', 'tok-from-query');

        expect((postArgs()[2] as any).headers['share-token']).toBe('tok-from-query');
    });

    it('round-trips the token from the opener through to the resolve call', async () => {
        const openSpy = jest.spyOn(window, 'open').mockImplementation(() => null);
        window.history.pushState({}, '', '/workspace/share/tok-2/SV-3');

        openHtmlArtifactViewer(
            { file_id: '1', file_name: 'r.html', file_url: 'linsight/final_result/y/r.html' },
            'SV-3',
        );
        const opened = new URL(openSpy.mock.calls[0][0] as string, 'http://localhost');
        openSpy.mockRestore();

        // What the freshly opened tab would do with its own query params.
        window.history.pushState({}, '', '/workspace/html');
        await resolveArtifactUrl(
            opened.searchParams.get('url') as string,
            opened.searchParams.get('vid') as string,
            opened.searchParams.get('share') || '',
        );

        expect((postArgs()[2] as any).headers['share-token']).toBe('tok-2');
    });
});
