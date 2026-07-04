import { applyHtmlViewerTabIdentity, openHtmlArtifactViewer, stripWorkspacePaths } from './artifactUtils';

describe('stripWorkspacePaths', () => {
    it('drops the output/ folder prefix, keeping the filename', () => {
        expect(stripWorkspacePaths('见 output/report.md')).toBe('见 report.md');
    });

    it('drops a leading-slash /output/ prefix (tool-result echo form)', () => {
        expect(stripWorkspacePaths('Updated file /output/knowledge_base_full.md')).toBe(
            'Updated file knowledge_base_full.md',
        );
    });

    it('strips the prefix inside a markdown code span, keeping the backticks', () => {
        expect(stripWorkspacePaths('导出到 `output/knowledge_base_full.md`，主要包括：')).toBe(
            '导出到 `knowledge_base_full.md`，主要包括：',
        );
    });

    it('handles scratch/ and multiple occurrences in one string', () => {
        expect(stripWorkspacePaths('output/a.md 与 scratch/b.docx')).toBe('a.md 与 b.docx');
    });

    it('leaves prose without a file token untouched (输入/输出, bare "output 文件夹")', () => {
        expect(stripWorkspacePaths('这是输入/输出分析，见 output 文件夹')).toBe('这是输入/输出分析，见 output 文件夹');
    });

    it('does not strip a mid-word match like myoutput/ (alphanumeric boundary)', () => {
        expect(stripWorkspacePaths('myoutput/a.md')).toBe('myoutput/a.md');
    });

    it('is safe on empty / undefined input', () => {
        expect(stripWorkspacePaths('')).toBe('');
        expect(stripWorkspacePaths(undefined as unknown as string)).toBe(undefined);
    });
});

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

describe('applyHtmlViewerTabIdentity', () => {
    const origEnv = (global as any).__APP_ENV__;
    const origTitle = document.title;

    beforeEach(() => {
        (global as any).__APP_ENV__ = { ...origEnv, BASE_URL: '/workspace' };
        document.head.innerHTML = '';
        document.title = 'BISHENG';
        delete (window as any).BRAND_CONFIG;
    });

    afterEach(() => {
        (global as any).__APP_ENV__ = origEnv;
        document.title = origTitle;
        delete (window as any).BRAND_CONFIG;
    });

    const favicon = () => document.head.querySelector<HTMLLinkElement>("link[rel~='icon']");

    // The report lives in a sandboxed iframe whose <head> can't reach this tab, so
    // the viewer must stamp the brand favicon onto the top-level /html document.
    it('applies the configured brand favicon to the tab', () => {
        (window as any).BRAND_CONFIG = { assets: { favicon: { url: '/workspace/brand-assets/favicon/custom.ico' } } };

        applyHtmlViewerTabIdentity('<html><head><title>Report</title></head><body></body></html>');

        expect(favicon()?.getAttribute('href')).toBe('/workspace/brand-assets/favicon/custom.ico');
    });

    it('falls back to the bundled default favicon when no brand favicon is configured', () => {
        applyHtmlViewerTabIdentity('<html><head><title>Report</title></head></html>');

        expect(favicon()?.getAttribute('href')).toBe('/workspace/assets/bisheng/favicon.ico');
    });

    // brand-runtime.js may have already created the icon link; reuse it instead of
    // appending a duplicate the browser might ignore.
    it('reuses an existing icon link instead of appending a duplicate', () => {
        const existing = document.createElement('link');
        existing.rel = 'icon';
        existing.href = '/old.ico';
        document.head.appendChild(existing);
        (window as any).BRAND_CONFIG = { assets: { favicon: { url: '/new.ico' } } };

        applyHtmlViewerTabIdentity('<html></html>');

        const links = document.head.querySelectorAll("link[rel~='icon']");
        expect(links.length).toBe(1);
        expect(favicon()?.getAttribute('href')).toBe('/new.ico');
    });

    it("sets the tab title to the report's own <title>", () => {
        applyHtmlViewerTabIdentity('<html><head><title>Seedmind</title></head><body></body></html>');

        expect(document.title).toBe('Seedmind');
    });

    it('leaves the brand title in place when the report has no <title>', () => {
        applyHtmlViewerTabIdentity('<html><body><p>no head title</p></body></html>');

        expect(document.title).toBe('BISHENG');
    });
});
