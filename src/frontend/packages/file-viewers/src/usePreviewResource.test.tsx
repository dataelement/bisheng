// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { usePreviewResource } from './usePreviewResource';
afterEach(cleanup);
function deferred<T>() {
  let resolve!: (data: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((accept, fail) => { resolve = accept; reject = fail; });
  return { promise, resolve, reject };
}
it('ignores the first A result after A to B to A and aborts the old requests', async () => {
  const reads: Array<ReturnType<typeof deferred<string>> & { signal: AbortSignal; id: string }> = [];
  const view = renderHook(({ id }) => usePreviewResource(id, signal => {
    const read = { ...deferred<string>(), signal, id }; reads.push(read); return read.promise;
  }), { initialProps: { id: 'A' } });
  view.rerender({ id: 'B' });
  view.rerender({ id: 'A' });
  expect(reads.map(read => read.id)).toEqual(['A','B','A']);
  expect(reads[0].signal.aborted).toBe(true);
  expect(reads[1].signal.aborted).toBe(true);
  await act(async () => { reads[2].resolve('current A'); });
  await act(async () => { reads[0].resolve('old A'); reads[1].reject(new Error('old B')); });
  expect(view.result.current).toMatchObject({ status: 'ready', data: 'current A' });
});
it('loads once even if the caller creates a new loader function every render', async () => {
  let calls = 0;
  const read = deferred<string>();
  const view = renderHook(() => usePreviewResource('same', async () => { calls++; return read.promise; }));
  view.rerender();
  await act(async () => { read.resolve('done'); });
  view.rerender();
  expect(calls).toBe(1);
  expect(view.result.current.data).toBe('done');
});
it('hides previous data immediately when selecting another file', async () => {
  const next = deferred<string>();
  const view = renderHook(({ id }) => usePreviewResource(id, async () => id === 'A' ? 'first' : next.promise), { initialProps: { id: 'A' } });
  await waitFor(() => expect(view.result.current.data).toBe('first'));
  view.rerender({ id: 'B' });
  expect(view.result.current).toMatchObject({ status: 'loading' });
  expect(view.result.current.data).toBeUndefined();
  await act(async () => { next.resolve('second'); });
  expect(view.result.current.data).toBe('second');
});
it('aborts on unmount and consumes late rejection', async () => {
  const read = deferred<string>(); let signal!: AbortSignal;
  const view = renderHook(() => usePreviewResource('A', current => { signal = current; return read.promise; }));
  view.unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => { read.reject(new Error('late failure')); });
});
it('retains failure evidence and starts fresh when reopening', async () => {
  const evidence = new Error('PRIVATE');
  const failed = renderHook(() => usePreviewResource('A', async () => { throw evidence; }));
  await waitFor(() => expect(failed.result.current.status).toBe('error'));
  expect(failed.result.current.error).toBe(evidence);
  failed.unmount();
  const reopened = renderHook(() => usePreviewResource('A', async () => 'recovered'));
  await waitFor(() => expect(reopened.result.current.data).toBe('recovered'));
});
