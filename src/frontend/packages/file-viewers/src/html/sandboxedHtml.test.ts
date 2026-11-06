import { runInNewContext } from 'node:vm';
import { expect, it } from 'vitest';
import { ARTIFACT_SANDBOX, buildSandboxedSrcDoc } from './sandboxedHtml';
it('keeps standards mode and installs storage before the document scripts', () => {
  const html = '<!DOCTYPE html><html><head><script>window.userCode = true;</script></head><body>File</body></html>';
  const result = buildSandboxedSrcDoc(html);
  expect(result.startsWith('<!DOCTYPE html>')).toBe(true);
  expect(result.indexOf('__bs_probe__')).toBeGreaterThan(0);
  expect(result.indexOf('__bs_probe__')).toBeLessThan(result.indexOf('window.userCode'));
  expect(result).toContain('<body>File</body>');
});
it('never grants host origin or popup escape while preserving script and download capabilities', () => {
  const tokens = ARTIFACT_SANDBOX.split(' ');
  expect(tokens).toContain('allow-scripts');
  expect(tokens).toContain('allow-downloads');
  expect(tokens).not.toContain('allow-same-origin');
  expect(tokens).not.toContain('allow-popups-to-escape-sandbox');
});
it('supplies memory-only storage when the sandbox denies real storage', () => {
  const fakeWindow: Partial<Pick<Window, 'localStorage' | 'sessionStorage'>> = {};
  for (const name of ['localStorage','sessionStorage']) Object.defineProperty(fakeWindow, name, { get() { throw new Error('Opaque origin'); }, configurable: true });
  const content = buildSandboxedSrcDoc('<!doctype html><p>Preview</p>');
  const script = content.match(/<script>([\s\S]*?)<\/script>/)?.[1];
  expect(script).toBeDefined();
  runInNewContext(script!, { window: fakeWindow });
  fakeWindow.localStorage!.setItem('page','2');
  expect(fakeWindow.localStorage!.getItem('page')).toBe('2');
  expect(fakeWindow.sessionStorage!.getItem('page')).toBeNull();
});
it('handles fragments and empty documents without losing their contents', () => {
  expect(buildSandboxedSrcDoc('')).toBe('');
  expect(buildSandboxedSrcDoc('<p>Preview</p>')).toContain('<p>Preview</p>');
});
