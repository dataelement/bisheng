import { ARTIFACT_SANDBOX, buildSandboxedSrcDoc } from './sandboxedHtml';

const SHIM_MARK = "window.localStorage.getItem('__bs_probe__')";

describe('buildSandboxedSrcDoc', () => {
    it('injects the storage shim right after <head> so it precedes the page scripts', () => {
        const out = buildSandboxedSrcDoc(
            '<!DOCTYPE html><html><head><script>window.a=1</script></head><body></body></html>',
        );
        expect(out.indexOf(SHIM_MARK)).toBeGreaterThan(-1);
        expect(out.indexOf(SHIM_MARK)).toBeLessThan(out.indexOf('window.a=1'));
    });

    // Anything placed before the doctype puts the document in quirks mode, which
    // would break the artifact's layout — a worse regression than the bug fixed here.
    it('never inserts ahead of the doctype', () => {
        const out = buildSandboxedSrcDoc('<!DOCTYPE html><html><head></head><body></body></html>');
        expect(out.startsWith('<!DOCTYPE html>')).toBe(true);
    });

    it('falls back to <html> when the document has no head', () => {
        const out = buildSandboxedSrcDoc('<!DOCTYPE html><html><body><script>window.a=1</script></body></html>');
        expect(out.indexOf(SHIM_MARK)).toBeLessThan(out.indexOf('window.a=1'));
        expect(out.startsWith('<!DOCTYPE html><html>')).toBe(true);
    });

    it('falls back to the doctype when the html tag is implicit', () => {
        const out = buildSandboxedSrcDoc('<!doctype html>\n<body><script>window.a=1</script></body>');
        expect(out.startsWith('<!doctype html>')).toBe(true);
        expect(out.indexOf(SHIM_MARK)).toBeLessThan(out.indexOf('window.a=1'));
    });

    it('prepends when the fragment has no document scaffolding at all', () => {
        const out = buildSandboxedSrcDoc('<div>hi</div>');
        expect(out.indexOf(SHIM_MARK)).toBeLessThan(out.indexOf('<div>hi</div>'));
    });

    it('handles attributes and casing on the head tag', () => {
        const out = buildSandboxedSrcDoc('<!DOCTYPE html><HTML><HEAD lang="zh"><title>t</title></HEAD></HTML>');
        expect(out.indexOf(SHIM_MARK)).toBeGreaterThan(out.indexOf('<HEAD lang="zh">'));
        expect(out.indexOf(SHIM_MARK)).toBeLessThan(out.indexOf('<title>'));
    });

    it('leaves empty input untouched', () => {
        expect(buildSandboxedSrcDoc('')).toBe('');
    });
});

describe('ARTIFACT_SANDBOX', () => {
    // Granting these to a srcDoc frame would hand the artifact this app's origin
    // (allow-same-origin) or an unsandboxed window at any URL.
    it('withholds the tokens that would break out of the sandbox', () => {
        expect(ARTIFACT_SANDBOX).not.toContain('allow-same-origin');
        expect(ARTIFACT_SANDBOX).not.toContain('allow-popups-to-escape-sandbox');
        expect(ARTIFACT_SANDBOX).toContain('allow-scripts');
    });
});
