// @vitest-environment jsdom
import { act, cleanup, render, waitFor } from '@testing-library/react';
import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { PdfPage } from './PdfPage';
function documentWith(renderResult:()=>Promise<void>) {
  const cancel=vi.fn();
  const page={getViewport:({scale}:{scale:number})=>({width:100*scale,height:200*scale}),render:vi.fn(()=>({promise:renderResult(),cancel}))} as unknown as PDFPageProxy;
  return {document:{getPage:vi.fn(async()=>page)} as unknown as PDFDocumentProxy,page,cancel};
}
beforeEach(()=>{vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({} as CanvasRenderingContext2D);});
afterEach(()=>{cleanup();vi.restoreAllMocks();});
it('renders the selected page once with consistent metrics and an overlay',async()=>{
  const fixture=documentWith(()=>Promise.resolve());const onMetrics=vi.fn();
  const view=render(<PdfPage pdfDoc={fixture.document} pageIndex={1} width={200} zoomLevel={100} onMetrics={onMetrics} renderOverlay={metrics=><span>{metrics.scale}</span>} />);
  await waitFor(()=>expect(fixture.page.render).toHaveBeenCalledTimes(1));
  expect(fixture.document.getPage).toHaveBeenCalledWith(2);
  expect(onMetrics).toHaveBeenCalledWith(expect.objectContaining({pageIndex:1,width:200,height:400,scale:2,originalWidth:100}));
  expect(view.container.querySelector('canvas')?.style.width).toBe('200px');
  expect(view.container.textContent).toBe('2');
});
it('uses a fresh canvas when zoom changes and cancels the prior task',async()=>{
  let finish!:()=>void;
  const fixture=documentWith(()=>new Promise<void>(resolve=>{finish=resolve;}));
  const view=render(<PdfPage pdfDoc={fixture.document} pageIndex={0} width={100} zoomLevel={100} />);
  await waitFor(()=>expect(fixture.page.render).toHaveBeenCalledTimes(1));
  const first=view.container.querySelector('canvas');
  view.rerender(<PdfPage pdfDoc={fixture.document} pageIndex={0} width={100} zoomLevel={150} />);
  await waitFor(()=>expect(fixture.page.render).toHaveBeenCalledTimes(2));
  expect(fixture.cancel).toHaveBeenCalled();
  expect(view.container.querySelector('canvas')).not.toBe(first);
  await act(async()=>{finish();});
});
it('ignores old-document failures after switching while retaining current failure evidence',async()=>{
  let rejectOld!:(error:unknown)=>void;
  const old=documentWith(()=>new Promise((_resolve,reject)=>{rejectOld=reject;}));
  const current=documentWith(()=>Promise.reject(new Error('current')));
  const onError=vi.fn();
  const view=render(<PdfPage pdfDoc={old.document} pageIndex={0} width={100} onError={onError} />);
  await waitFor(()=>expect(old.page.render).toHaveBeenCalled());
  view.rerender(<PdfPage pdfDoc={current.document} pageIndex={0} width={100} onError={onError} />);
  await waitFor(()=>expect(onError).toHaveBeenCalledTimes(1));
  await act(async()=>{rejectOld(new Error('old'));});
  expect(onError).toHaveBeenCalledTimes(1);
});
it('ignores a normal rendering cancellation',async()=>{
  const fixture=documentWith(()=>Promise.reject(Object.assign(new Error('stop'),{name:'RenderingCancelledException'})));
  const onError=vi.fn();
  render(<PdfPage pdfDoc={fixture.document} pageIndex={0} width={100} onError={onError} />);
  await waitFor(()=>expect(fixture.page.render).toHaveBeenCalled());
  expect(onError).not.toHaveBeenCalled();
});
