import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useCitationPreview } from './useCitationPreview';
import type { CitationDocumentPreviewState, CitationServices } from './types';
const preview=(id:string):CitationDocumentPreviewState=>({detail:{citationId:id,type:'knowledgeSearch',sourcePayload:{documentName:id+'.pdf',items:[{itemId:'a',bbox:'{"chunk_bboxes":[{"page":0,"bbox":[1,2,3,4]}]}'}]}},itemIds:['a'],locateChunk:true});
const service=():CitationServices=>({scopeKey:'one',localize:key=>key,getCitationDetail:vi.fn(),resolveCitationDetails:vi.fn(),getCitationUnresolvedReason:()=>undefined,resolveDocumentUrls:vi.fn().mockResolvedValue({originalUrl:'file.docx',previewUrl:'file.pdf'}),download:vi.fn(),openArticle:vi.fn()});
afterEach(cleanup);
it('keeps original download separate and prepares stable multi-passage PDF boxes',async()=>{
 const services=service();const selected=preview('A');const view=renderHook(()=>useCitationPreview(selected,services));
 await waitFor(()=>expect(view.result.current.status).toBe('ready'));
 expect(view.result.current.fileUrl).toBe('file.pdf');expect(view.result.current.bboxes).toHaveLength(1);
 const boxes=view.result.current.bboxes;view.rerender();expect(view.result.current.bboxes).toBe(boxes);
 await view.result.current.download();expect(services.download).toHaveBeenCalledWith('file.docx','A.pdf');
});
it('ignores old A and B completions in an A to B to A selection sequence',async()=>{
 const services=service();const finish:((urls:{originalUrl:string;previewUrl:string})=>void)[]=[];
 vi.mocked(services.resolveDocumentUrls).mockImplementation(()=>new Promise(resolve=>finish.push(resolve)));
 const a=preview('A'),b=preview('B');const view=renderHook(({selected})=>useCitationPreview(selected,services),{initialProps:{selected:a}});
 await waitFor(()=>expect(finish).toHaveLength(1));view.rerender({selected:b});await waitFor(()=>expect(finish).toHaveLength(2));
 view.rerender({selected:a});await waitFor(()=>expect(finish).toHaveLength(3));
 await act(async()=>{finish[0]({originalUrl:'oldA',previewUrl:'oldA.pdf'});finish[1]({originalUrl:'B',previewUrl:'B.pdf'});});
 expect(view.result.current.status).toBe('loading');expect(view.result.current.fileUrl).toBe('');
 await act(async()=>finish[2]({originalUrl:'newA',previewUrl:'newA.pdf'}));expect(view.result.current.fileUrl).toBe('newA.pdf');
});
it('denial ends loading without asking for a resource or retaining a legacy URL',async()=>{
 const services=service();services.getCitationUnresolvedReason=()=> 'forbidden';
 const selected=preview('denied');selected.detail.sourcePayload!.downloadUrl='old.pdf';
 const view=renderHook(()=>useCitationPreview(selected,services));
 await waitFor(()=>expect(view.result.current.status).toBe('error'));
 expect(services.resolveDocumentUrls).not.toHaveBeenCalled();expect(view.result.current.fileUrl).toBe('');
});
it('starts a fresh resource read when the access scope changes and never downloads after unmount',async()=>{
 const services=service();const selected=preview('A');const view=renderHook(({scope})=>useCitationPreview(selected,{...services,scopeKey:scope}),{initialProps:{scope:'A'}});
 await waitFor(()=>expect(view.result.current.status).toBe('ready'));const staleDownload=view.result.current.download;
 view.rerender({scope:'B'});expect(view.result.current.fileUrl).toBe('');await waitFor(()=>expect(services.resolveDocumentUrls).toHaveBeenCalledTimes(2));
 view.unmount();await staleDownload();expect(services.download).not.toHaveBeenCalled();
});
