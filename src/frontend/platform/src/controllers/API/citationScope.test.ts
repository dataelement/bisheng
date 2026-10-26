import { afterEach, expect, it, vi } from 'vitest';
import request from '../request';
import { getCitationDetail, resolveCitationDetails } from './index';
vi.mock('../request',()=>({default:{get:vi.fn(),post:vi.fn()}}));
afterEach(()=>localStorage.clear());
it('isolates cached details across platform identities',async()=>{
 vi.mocked(request.get).mockResolvedValueOnce({citationId:'scoped-platform',type:'web',sourcePayload:{title:'A'}}).mockResolvedValueOnce({citationId:'scoped-platform',type:'web',sourcePayload:{title:'B'}});
 localStorage.setItem('UUR_INFO','A');expect((await getCitationDetail('scoped-platform')).sourcePayload?.title).toBe('A');
 localStorage.setItem('UUR_INFO','B');expect((await getCitationDetail('scoped-platform')).sourcePayload?.title).toBe('B');
});
it('does not reuse an in-flight batch after switching platform identities',async()=>{
 let finish!:(value:unknown)=>void;
 vi.mocked(request.post).mockReturnValueOnce(new Promise(resolve=>{finish=resolve;}) as ReturnType<typeof request.post>).mockResolvedValueOnce({items:[{citationId:'scoped-batch',type:'web',sourcePayload:{title:'B'}}]});
 localStorage.setItem('UUR_INFO','A');const old=resolveCitationDetails(['scoped-batch']);
 localStorage.setItem('UUR_INFO','B');const current=resolveCitationDetails(['scoped-batch']);
 expect(request.post).toHaveBeenCalledTimes(2);expect((await current)[0]?.sourcePayload?.title).toBe('B');
 finish({items:[{citationId:'scoped-batch',type:'web',sourcePayload:{title:'A'}}]});await old;
 expect((await getCitationDetail('scoped-batch')).sourcePayload?.title).toBe('B');
});
