import { fireEvent, render, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { PlatformPdfPreview } from './PlatformPdfPreview';
const { document } = vi.hoisted(()=>({document:{numPages:400}}));
vi.mock('@bisheng/file-viewers/pdf',async importOriginal=>{
  const original=await importOriginal<typeof import('@bisheng/file-viewers/pdf')>();
  return {...original,usePdfDocument:()=>({status:'ready',document}),PdfPage:({pageIndex,width,renderOverlay}:{pageIndex:number;width:number;renderOverlay?:(metrics:{width:number;height:number;scale:number})=>React.ReactNode})=><div data-pdf-page={pageIndex} style={{width,height:width*2}}>{renderOverlay?.({width,height:width*2,scale:width/100})}</div>};
});
beforeEach(()=>{
  vi.spyOn(HTMLElement.prototype,'clientWidth','get').mockReturnValue(200);
  vi.spyOn(HTMLElement.prototype,'clientHeight','get').mockReturnValue(400);
});
it('renders a bounded virtual window independently for multiple previews',async()=>{
  const view=render(<><PlatformPdfPreview fileUrl="/a.pdf"/><PlatformPdfPreview fileUrl="/b.pdf"/></>);
  await waitFor(()=>expect(view.container.querySelectorAll('[data-pdf-page]').length).toBeGreaterThan(1));
  expect(view.container.querySelectorAll('[data-pdf-page]').length).toBeLessThan(30);
  expect(view.container.querySelectorAll('#warp-pdf')).toHaveLength(0);
});
it('only permits label writes in edit mode and scopes dragging to its own viewport',async()=>{
  const onSelectLabel=vi.fn();const labels={0:[{id:'a',label:[10,20,30,40],active:false}]};
  const view=render(<PlatformPdfPreview startIndex={0} fileUrl="/a.pdf" labels={labels} onSelectLabel={onSelectLabel}/>);
  await waitFor(()=>expect(view.container.querySelector('rect')).not.toBeNull());
  fireEvent.click(view.container.querySelector('rect')!);expect(onSelectLabel).not.toHaveBeenCalled();
  view.rerender(<PlatformPdfPreview select startIndex={0} fileUrl="/a.pdf" labels={labels} onSelectLabel={onSelectLabel}/>);
  fireEvent.click(view.container.querySelector('rect')!);expect(onSelectLabel).toHaveBeenCalledWith([{id:'a',active:true}]);
  onSelectLabel.mockClear();fireEvent.mouseDown(window,{clientX:0,clientY:0});fireEvent.mouseMove(window,{clientX:200,clientY:200});fireEvent.mouseUp(window,{clientX:200,clientY:200});
  expect(onSelectLabel).not.toHaveBeenCalled();
});
