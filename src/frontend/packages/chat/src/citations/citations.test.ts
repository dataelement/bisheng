// @vitest-environment node
import { expect, it, vi } from 'vitest';
import { createCitationUtilities, transformPrivateCitations, parseLegacyWebCitationContent, createCitationResourceResolver } from './index';
import type { ChatCitation } from './types';
const localize=(key:string,options?:Record<string,unknown>)=>key+String(options?.[0]??'');
const utils=createCitationUtilities(localize);
const detail:ChatCitation={citationId:'knowledgeSearch_doc',type:'knowledgeSearch',sourcePayload:{documentId:12,documentName:'policy.pdf',items:[{itemId:'a',page:0,bbox:JSON.stringify({chunk_bboxes:[{page:0,bbox:[1,2,3,4]}]})},{itemId:'b',chunkIndex:3}]}};
it('preserves old marker numbering and groups every cited chunk in first-source order',()=>{
 const content='xknowledgeSearch_doc:awebSearch_site:1yknowledgeSearch_doc:bknowledgeSearch_doc:a';
 const refs=utils.buildCitationReferenceItems({content,citations:[detail]});
 expect(refs.map(item=>item.data.citationId)).toEqual(['knowledgeSearch_doc','webSearch_site']);
 expect(refs[0].itemIds).toEqual(['a','b']);
 expect(Object.values(transformPrivateCitations(content).citationMap).map(item=>item.label)).toEqual([1,2,3]);
 expect(utils.getCitationItemBBoxes(detail,['a','b'])).toEqual([{page:0,bbox:[1,2,3,4]}]);
});
it('retains legacy web content and refuses malformed references',()=>{
 const parsed=parseLegacyWebCitationContent('body:::web[{"title":"old","url":"https://example.com"}]:::');
 expect(parsed.content).toBe('body');
 expect(utils.buildCitationReferenceItems({content:'[citation:1]',webContent:parsed.webContent})[0].legacyPreview?.title).toBe('old');
 expect(transformPrivateCitations('not-a-reference').citationMap).toEqual({});
});
it('bakes resolvable references while keeping code literal and stripping unresolved handles',()=>{
 const text='answerknowledgeSearch_doc:a [S9] `x[S1]`';
 expect(utils.bakeCitationsForExport(text,{[detail.citationId]:detail},'References')).toContain('1. 《policy.pdf》');
 expect(utils.bakeCitationsForExport(text,{},'References')).toBe('answer  `x[S1]`');
});
it('keeps temporary originals and previews separate without calling knowledge share',async()=>{
 const read=vi.fn();const resolve=createCitationResourceResolver(read);
 const urls=await resolve({citationId:'tempSearch_x',type:'tempSearch',sourcePayload:{downloadUrl:'clip.mp4',previewUrl:'clip.md'}},'scope');
 expect(urls).toEqual({originalUrl:'clip.mp4',previewUrl:'clip.md'});expect(read).not.toHaveBeenCalled();
});
it('deduplicates only in-flight requests within one access scope and never falls back after denial',async()=>{
 const finishes: ((value:{originalUrl:string;previewUrl:string})=>void)[]=[];
 const read=vi.fn(()=>new Promise<{originalUrl:string;previewUrl:string}>(resolve=>{finishes.push(resolve);}));
 const resolve=createCitationResourceResolver(read);
 const a=resolve(detail,'A');const same=resolve(detail,'A');const b=resolve(detail,'B');
 expect(read).toHaveBeenCalledTimes(2);finishes[1]({originalUrl:'B',previewUrl:'B-preview'});await b;
 expect(a).toBe(same);finishes[0]({originalUrl:'A',previewUrl:'A-preview'});await a;
 const denied=createCitationResourceResolver(vi.fn().mockRejectedValue(Object.assign(new Error('denied'),{status:403})));
 await expect(denied({...detail,sourcePayload:{...detail.sourcePayload,downloadUrl:'old'}},'A')).rejects.toMatchObject({status:403});
});
