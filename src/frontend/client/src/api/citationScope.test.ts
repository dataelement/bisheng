import request from './request';
import { getCitationDetail, resolveCitationDetails } from './chatApi';
jest.mock('./request',()=>({__esModule:true,default:{get:jest.fn(),post:jest.fn()}}));
afterEach(()=>localStorage.clear());
it('does not reuse citation details after switching the current account',async()=>{
 (request.get as jest.Mock).mockResolvedValueOnce({citationId:'scope-doc',type:'web',sourcePayload:{title:'A'}}).mockResolvedValueOnce({citationId:'scope-doc',type:'web',sourcePayload:{title:'B'}});
 localStorage.setItem('bs:auth-state','A');expect((await getCitationDetail('scope-doc')).sourcePayload?.title).toBe('A');
 localStorage.setItem('bs:auth-state','B');expect((await getCitationDetail('scope-doc')).sourcePayload?.title).toBe('B');
});
it('keeps late in-flight results in their original access scope',async()=>{
 let finish!:(value:unknown)=>void;
 (request.post as jest.Mock).mockReturnValueOnce(new Promise(resolve=>{finish=resolve;})).mockResolvedValueOnce({items:[{citationId:'scope-late',type:'web',sourcePayload:{title:'B'}}]});
 localStorage.setItem('bs:auth-state','A');const old=resolveCitationDetails(['scope-late']);
 localStorage.setItem('bs:auth-state','B');const current=await resolveCitationDetails(['scope-late']);
 expect(current[0]?.sourcePayload?.title).toBe('B');
 finish({items:[{citationId:'scope-late',type:'web',sourcePayload:{title:'A'}}]});await old;
 expect((await getCitationDetail('scope-late')).sourcePayload?.title).toBe('B');
});
