import { IDBFactory } from 'fake-indexeddb';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
let withAuthLock: typeof import('./authCoordination').withAuthLock;

beforeEach(async () => {
  vi.resetModules();
  vi.stubGlobal('navigator', {}); vi.stubGlobal('indexedDB', new IDBFactory());
  withAuthLock = (await import('./authCoordination')).withAuthLock;
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
const tick = () => new Promise(resolve => setTimeout(resolve, 10));
describe('browser authentication mutual exclusion', () => {
  it('uses Web Locks when supported', async () => {
    const request = vi.fn((_name: string, _options: unknown, callback: () => unknown) => callback());
    vi.stubGlobal('navigator', { locks: { request } });
    await expect(withAuthLock(async current => current())).resolves.toBe(true);
    expect(request).toHaveBeenCalledOnce();
  });
  it.each([true, false])('serializes independent callers with IndexedDB, native randomUUID=%s', async nativeUuid => {
    if (!nativeUuid) {
      const getRandomValues = crypto.getRandomValues.bind(crypto);
      vi.stubGlobal('crypto', { getRandomValues });
      expect(crypto.randomUUID).toBeUndefined();
      await expect(withAuthLock(async current => current())).resolves.toBe(true);
    }
    let release: (() => void) | undefined;
    const order: string[] = [];
    const first = withAuthLock(async current => {
      order.push('first');
      await new Promise<void>(resolve => { release = resolve; });
      expect(current()).toBe(true);
    });
    while (!release) await tick();
    const second = withAuthLock(async () => { order.push('second'); });
    await tick();
    expect(order).toEqual(['first']);
    release();
    await Promise.all([first, second]);
    expect(order).toEqual(['first', 'second']);
  });
  it('fails closed when neither coordination primitive exists', async () => {
    vi.stubGlobal('indexedDB', undefined);
    await expect(withAuthLock(async () => true)).rejects.toMatchObject({ code: 10659, retryable: true });
  });
});

it('fences a suspended owner after another tab takes its expired lease', async () => {
  vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] });
  let release: (() => void) | undefined;
  let oldCurrent: (() => boolean) | undefined;
  const first = withAuthLock(async current => {
    oldCurrent = current;
    await new Promise<void>(resolve => { release = resolve; });
    expect(current()).toBe(false);
  });
  while (!release) await tick();
  vi.setSystemTime(Date.now() + 16000);
  expect(oldCurrent?.()).toBe(false);
  await withAuthLock(async current => { expect(current()).toBe(true); });
  release();
  await first;
  // The late owner's release must not mutate its successor's fence.
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open('bisheng-auth-coordination', 1);
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
  const lease = await new Promise<{ fence: number; until: number }>(resolve => {
    const request = db.transaction('leases').objectStore('leases').get('bisheng:platform-auth');
    request.onsuccess = () => resolve(request.result);
  });
  expect(lease).toMatchObject({ fence: 2, until: 0 });
  db.close();
});
it('uses the lease fallback when the Web Locks API rejects before acquisition', async () => {
  vi.stubGlobal('navigator', { locks: { request: () => Promise.reject(new Error('disabled')) } });
  await expect(withAuthLock(async current => current())).resolves.toBe(true);
});
it('does not retry a completed lock callback through a second coordination transport', async () => {
  vi.stubGlobal('navigator', { locks: { request: (_name: unknown, _options: unknown, callback: () => unknown) => callback() } });
  const callback = vi.fn(async () => { throw new Error('business failure'); });
  await expect(withAuthLock(callback)).rejects.toThrow('business failure');
  expect(callback).toHaveBeenCalledOnce();
});
