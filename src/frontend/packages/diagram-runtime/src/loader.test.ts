// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { loadDiagramLibrary as Loader } from './loader';
let load: typeof Loader;
const browser = window as Window & { echarts?: unknown; mermaid?: unknown };
beforeEach(async () => {
  vi.resetModules();
  vi.useFakeTimers();
  document.head.innerHTML = '';
  delete browser.echarts;
  delete browser.mermaid;
  load = (await import('./loader')).loadDiagramLibrary;
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
function script() { return document.querySelector('script')!; }
it('shares one in-flight script and promise for concurrent consumers', async () => {
  const first = load('echarts', { baseUrl: '/workspace/' });
  expect(load('echarts', { baseUrl: '/workspace' })).toBe(first);
  expect(script().getAttribute('src')).toBe('/workspace/echarts.min.js');
  expect(document.querySelectorAll('script')).toHaveLength(1);
  const runtime = browser.echarts = { version: 'existing' };
  script().dispatchEvent(new Event('load'));
  expect(await first).toBe(runtime);
  expect(vi.getTimerCount()).toBe(0);
});
it('uses an existing global without adding a script', async () => {
  const runtime = browser.mermaid = {};
  expect(await load('mermaid', { baseUrl: '' })).toBe(runtime);
  expect(document.querySelectorAll('script')).toHaveLength(0);
});
it('does not start another version while the same kind loads from a different base', async () => {
  const first = load('mermaid', { baseUrl: '/workspace' });
  expect(load('mermaid', { baseUrl: '/admin' })).toBe(first);
  browser.mermaid = {};
  script().dispatchEvent(new Event('load'));
  await first;
});
it('cleans failed loads and allows a fresh attempt', async () => {
  const first = load('echarts', { baseUrl: '' });
  const rejected = expect(first).rejects.toThrow('load echarts');
  script().dispatchEvent(new Event('error'));
  await rejected;
  expect(document.querySelectorAll('script')).toHaveLength(0);
  expect(vi.getTimerCount()).toBe(0);
  const retry = load('echarts', { baseUrl: '' });
  expect(script().getAttribute('src')).toBe('/echarts.min.js');
  browser.echarts = {};
  script().dispatchEvent(new Event('load'));
  await retry;
});
it('times out even when onload fires without initializing the global, then retries', async () => {
  const first = load('mermaid', { baseUrl: '', timeoutMs: 100 });
  const oldScript = script();
  const lateLoad = oldScript.onload;
  const rejected = expect(first).rejects.toThrow('Timed out');
  oldScript.dispatchEvent(new Event('load'));
  await vi.advanceTimersByTimeAsync(100);
  await rejected;
  expect(vi.getTimerCount()).toBe(0);
  const retry = load('mermaid', { baseUrl: '' });
  const currentScript = script();
  const runtime = browser.mermaid = {};
  lateLoad?.call(oldScript, new Event('load'));
  expect(document.querySelectorAll('script')).toHaveLength(1);
  currentScript.dispatchEvent(new Event('load'));
  expect(await retry).toBe(runtime);
  expect(vi.getTimerCount()).toBe(0);
});
it('waits for initialization after the script finishes loading', async () => {
  const first = load('echarts', { baseUrl: '' });
  script().dispatchEvent(new Event('load'));
  const runtime = browser.echarts = {};
  await vi.advanceTimersByTimeAsync(50);
  expect(await first).toBe(runtime);
});
it('can be imported without DOM and rejects loading without a browser', async () => {
  vi.stubGlobal('document', undefined);
  await expect(load('echarts', { baseUrl: '' })).rejects.toThrow('browser');
});
