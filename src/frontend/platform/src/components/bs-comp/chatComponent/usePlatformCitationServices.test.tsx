import { act,cleanup,render,renderHook,waitFor } from '@testing-library/react';
import { afterEach,expect,it,vi } from 'vitest';
import { CitationDocumentPreview } from '@bisheng/chat/citation-views';
import type { ChatCitation } from '@bisheng/chat/citations';
import request from '@/controllers/request';
import { usePlatformCitationServices } from './usePlatformCitationServices';
vi.mock('@/controllers/request',()=>({default:{get:vi.fn(),post:vi.fn()}}));
const seeded:ChatCitation={citationId:'knowledgeSearch_refresh_signature',type:'knowledgeSearch',sourcePayload:{documentName:'note.txt',previewUrl:'https://storage.example/old.txt',downloadUrl:'https://storage.example/original.txt'}};
function Preview({visible}:{visible:boolean}){const services=usePlatformCitationServices();return <CitationDocumentPreview preview={visible?{detail:seeded}:null} services={services} renderFile={props=><div data-testid="file">{props.fileUrl}</div>}/>;}
afterEach(()=>{cleanup();localStorage.clear();vi.clearAllMocks();});
it('refreshes a signed citation through the same permission endpoint after closing and reopening',async()=>{
 vi.mocked(request.get).mockResolvedValueOnce(seeded).mockResolvedValueOnce({...seeded,sourcePayload:{...seeded.sourcePayload,previewUrl:'https://storage.example/new.txt'}});
 const view=render(<Preview visible/>);
 await waitFor(()=>expect(view.getByTestId('file').textContent).toContain('old.txt'));
 view.rerender(<Preview visible={false}/>);view.rerender(<Preview visible/>);
 await waitFor(()=>expect(view.getByTestId('file').textContent).toContain('new.txt'));
 expect(request.get).toHaveBeenCalledTimes(2);
 expect(request.get).toHaveBeenLastCalledWith('/api/v1/citations/knowledgeSearch_refresh_signature',{silent:true});
});
it('keeps a refreshed permission denial unavailable instead of reusing the seeded signature',async()=>{
 vi.mocked(request.get).mockRejectedValueOnce({response:{data:{status_code:404,reason:'forbidden'}}});
 const view=render(<Preview visible/>);
 await waitFor(()=>expect(view.getByText('shared:citations.com_citation.preview_unavailable')).toBeTruthy());
 expect(view.queryByTestId('file')).toBeNull();
});

it('opens a complete temporary source without requiring registry metadata',async()=>{
 const {result}=renderHook(()=>usePlatformCitationServices());
 const resource=await result.current.resolveDocumentUrls({citationId:'tempSearch_seed',type:'tempSearch',sourcePayload:{documentName:'temporary.txt',sourceUrl:'/temporary.txt'}});
 expect(resource.previewUrl).toContain('/temporary.txt');expect(request.get).not.toHaveBeenCalled();
});
it('shares only the pending refresh when two preview consumers open the same source',async()=>{
 let finish!:(detail:ChatCitation)=>void;
 vi.mocked(request.get).mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
 const {result}=renderHook(()=>usePlatformCitationServices());
 const first=result.current.resolveDocumentUrls({...seeded,citationId:'knowledgeSearch_concurrent'});
 const second=result.current.resolveDocumentUrls({...seeded,citationId:'knowledgeSearch_concurrent'});
 expect(request.get).toHaveBeenCalledTimes(1);
 await act(async()=>finish({...seeded,citationId:'knowledgeSearch_concurrent'}));
 await Promise.all([first,second]);
});
