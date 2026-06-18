import { openHtmlArtifactViewer } from './artifactUtils';

describe('openHtmlArtifactViewer', () => {
    const origEnv = (global as any).__APP_ENV__;
    let openSpy: jest.SpyInstance;

    beforeEach(() => {
        (global as any).__APP_ENV__ = { ...origEnv, BASE_URL: '/workspace' };
        openSpy = jest.spyOn(window, 'open').mockImplementation(() => null);
    });

    afterEach(() => {
        (global as any).__APP_ENV__ = origEnv;
        openSpy.mockRestore();
    });

    // Regression: file_url is a MinIO object key (no leading slash). The old code
    // concatenated it straight onto BASE_URL → `/workspacelinsight/...` (missing
    // slash 404). It must instead go through the /html viewer as a query param,
    // carrying the vid so the viewer can resolve a presigned link.
    it('passes url + vid as query params and never concatenates the key onto BASE_URL', () => {
        openHtmlArtifactViewer(
            {
                file_id: '1',
                file_name: '减肥计划.html',
                file_url: 'linsight/final_result/abc/减肥计划.html',
            },
            'SV-1',
        );

        expect(openSpy).toHaveBeenCalledTimes(1);
        const opened = openSpy.mock.calls[0][0] as string;

        expect(opened).not.toContain('/workspacelinsight');
        expect(opened.startsWith('/workspace/html?')).toBe(true);

        const qs = new URLSearchParams(opened.split('?')[1]);
        expect(qs.get('url')).toBe('linsight/final_result/abc/减肥计划.html');
        expect(qs.get('vid')).toBe('SV-1');
        expect(openSpy.mock.calls[0][1]).toBe('_blank');
    });

    it('tolerates an empty versionId (vid present but blank)', () => {
        openHtmlArtifactViewer(
            { file_id: '2', file_name: 'a.html', file_url: 'linsight/final_result/x/a.html' },
            '',
        );
        const opened = openSpy.mock.calls[0][0] as string;
        const qs = new URLSearchParams(opened.split('?')[1]);
        expect(qs.get('vid')).toBe('');
        expect(qs.get('url')).toBe('linsight/final_result/x/a.html');
    });
});
