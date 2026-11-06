// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { usePdfDocument } from './usePdfDocument';
const { load, worker } = vi.hoisted(()=>({load:vi.fn(),worker:{workerSrc:''}}));
vi.mock('pdfjs-dist',()=>({getDocument:load,GlobalWorkerOptions:worker}));
const assets={workerUrl:'/workspace/pdf.worker.min.js',cMapUrl:'/workspace/cmaps/'};
beforeEach(()=>{load.mockReset();});afterEach(cleanup);
it('uses host worker/CMaps and destroys the document task when closing',async()=>{
  const destroy=vi.fn().mockResolvedValue(undefined);const document={numPages:2};
  load.mockReturnValue({promise:Promise.resolve(document),destroy});
  const view=renderHook(()=>usePdfDocument('/signed.pdf',assets));
  await waitFor(()=>expect(view.result.current.document).toBe(document));
  expect(worker.workerSrc).toBe(assets.workerUrl);
  expect(load).toHaveBeenCalledWith({url:'/signed.pdf',cMapUrl:assets.cMapUrl,cMapPacked:true});
  view.unmount();expect(destroy).toHaveBeenCalledTimes(1);
});
it('destroys and ignores a pending old document when changing files',async()=>{
  let resolveOld!:(value:unknown)=>void;const destroy=vi.fn().mockResolvedValue(undefined);
  load.mockReturnValueOnce({promise:new Promise(resolve=>{resolveOld=resolve;}),destroy});
  const current={numPages:1};load.mockReturnValueOnce({promise:Promise.resolve(current),destroy:vi.fn().mockResolvedValue(undefined)});
  const view=renderHook(({url})=>usePdfDocument(url,assets),{initialProps:{url:'/A.pdf'}});
  await waitFor(()=>expect(load).toHaveBeenCalledTimes(1));
  view.rerender({url:'/B.pdf'});
  await waitFor(()=>expect(view.result.current.document).toBe(current));
  await act(async()=>{resolveOld({numPages:99});});
  expect(view.result.current.document).toBe(current);expect(destroy).toHaveBeenCalledTimes(1);
});
it('does not load PDF.js for an inactive preview',async()=>{
  const view=renderHook(()=>usePdfDocument('',assets));
  await waitFor(()=>expect(view.result.current.status).toBe('ready'));
  expect(load).not.toHaveBeenCalled();expect(view.result.current.document).toBeNull();
});
