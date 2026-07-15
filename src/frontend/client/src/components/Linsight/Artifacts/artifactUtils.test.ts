import {
    type ArtifactFile,
    applyHtmlViewerTabIdentity,
    isAbsoluteImageSrc,
    matchArtifactByRelPath,
    openHtmlArtifactViewer,
    stripEmptyHtmlPlaceholders,
    stripWorkspacePaths,
} from './artifactUtils';

const mkArtifact = (over: Partial<ArtifactFile>): ArtifactFile => ({
    file_id: over.file_id ?? Math.random().toString(36).slice(2),
    file_name: over.file_name ?? 'x.png',
    file_url: over.file_url ?? 'linsight/final_result/svid/rand.png',
    file_path: over.file_path,
    ...over,
});

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

describe('isAbsoluteImageSrc', () => {
    it('treats http(s) / protocol-relative / data / blob / root-relative as absolute', () => {
        expect(isAbsoluteImageSrc('https://x/y.png')).toBe(true);
        expect(isAbsoluteImageSrc('http://x/y.png')).toBe(true);
        expect(isAbsoluteImageSrc('//x/y.png')).toBe(true);
        expect(isAbsoluteImageSrc('data:image/png;base64,AAAA')).toBe(true);
        expect(isAbsoluteImageSrc('blob:https://x/uuid')).toBe(true);
        expect(isAbsoluteImageSrc('/workspace/y.png')).toBe(true);
    });

    it('treats a bare relative ref as NOT absolute (goes through resolution)', () => {
        expect(isAbsoluteImageSrc('charts/ch1_brazil.png')).toBe(false);
        expect(isAbsoluteImageSrc('./charts/x.png')).toBe(false);
        expect(isAbsoluteImageSrc('output/charts/x.png')).toBe(false);
    });
});

describe('matchArtifactByRelPath', () => {
    // file_path is the worker-local abs path; it preserves the relative dir suffix.
    const brazil = mkArtifact({
        file_name: 'ch1_brazil.png',
        file_url: 'linsight/final_result/svid/aaaa1111.png',
        file_path: '/cache/linsight/01b4635d/output/charts/ch1_brazil.png',
    });
    const argentina = mkArtifact({
        file_name: 'ch1_argentina.png',
        file_url: 'linsight/final_result/svid/bbbb2222.png',
        file_path: '/cache/linsight/01b4635d/output/charts/ch1_argentina.png',
    });
    const list = [brazil, argentina];

    it('matches a bare `charts/x.png` ref by file_path suffix', () => {
        expect(matchArtifactByRelPath(list, 'charts/ch1_brazil.png')).toBe(brazil);
    });

    it('matches when the ref carries the output/ prefix too', () => {
        expect(matchArtifactByRelPath(list, 'output/charts/ch1_argentina.png')).toBe(argentina);
    });

    it('tolerates a leading ./', () => {
        expect(matchArtifactByRelPath(list, './charts/ch1_brazil.png')).toBe(brazil);
    });

    it('decodes URL-encoded (e.g. Chinese) filenames before matching', () => {
        const cn = mkArtifact({
            file_name: 'ch3_艾奥瓦豆油基差.png',
            file_path: '/cache/linsight/01b4635d/output/charts/ch3_艾奥瓦豆油基差.png',
        });
        expect(matchArtifactByRelPath([cn], 'charts/ch3_%E8%89%BE%E5%A5%A5%E7%93%A6%E8%B1%86%E6%B2%B9%E5%9F%BA%E5%B7%AE.png')).toBe(cn);
    });

    it('disambiguates same basename in different dirs via the path suffix', () => {
        const a = mkArtifact({ file_name: 'chart.png', file_path: '/w/output/charts/chart.png' });
        const b = mkArtifact({ file_name: 'chart.png', file_path: '/w/output/other/chart.png' });
        expect(matchArtifactByRelPath([a, b], 'charts/chart.png')).toBe(a);
        expect(matchArtifactByRelPath([a, b], 'other/chart.png')).toBe(b);
    });

    it('falls back to a bare basename match when file_path is absent', () => {
        const noPath = mkArtifact({ file_name: 'ch1_brazil.png', file_path: undefined });
        expect(matchArtifactByRelPath([noPath], 'charts/ch1_brazil.png')).toBe(noPath);
    });

    it('returns undefined on no match / empty list / empty ref', () => {
        expect(matchArtifactByRelPath(list, 'charts/nope.png')).toBeUndefined();
        expect(matchArtifactByRelPath([], 'charts/ch1_brazil.png')).toBeUndefined();
        expect(matchArtifactByRelPath(undefined, 'charts/ch1_brazil.png')).toBeUndefined();
        expect(matchArtifactByRelPath(list, '')).toBeUndefined();
    });
});

describe('stripEmptyHtmlPlaceholders', () => {
    it('removes an empty styled <div></div> placeholder box (the leaked-noise case)', () => {
        const md = '正文\n\n<div style="border:1px solid #ccc; height:120px; background:#f9f9f9;"></div>\n\n更多';
        expect(stripEmptyHtmlPlaceholders(md)).toBe('正文\n\n\n\n更多');
    });

    it('removes multiple and simply-nested empty blocks', () => {
        expect(stripEmptyHtmlPlaceholders('<div></div><section class="a"></section>')).toBe('');
        expect(stripEmptyHtmlPlaceholders('<div><div></div></div>')).toBe('');
    });

    it('keeps content-bearing HTML untouched (only EMPTY tags are stripped)', () => {
        expect(stripEmptyHtmlPlaceholders('<div>评论：看多</div>')).toBe('<div>评论：看多</div>');
    });

    it('leaves normal markdown (incl. image syntax) untouched', () => {
        const md = '# 标题\n\n![季节性走势](charts/x.png)\n\n段落';
        expect(stripEmptyHtmlPlaceholders(md)).toBe(md);
    });

    it('is safe on empty / undefined input', () => {
        expect(stripEmptyHtmlPlaceholders('')).toBe('');
        expect(stripEmptyHtmlPlaceholders(undefined as unknown as string)).toBe(undefined);
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
