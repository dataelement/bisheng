import { render,waitFor } from '@testing-library/react';
import { CitationDocumentPreviewContent } from './CitationDocumentPreviewDrawer';
import { getFilePathApi } from '~/api/chat/data-service';
import { getCitationUnresolvedReason } from '~/api/chatApi';
import type { ChatCitation } from '@bisheng/chat/citations';
jest.mock('~/hooks',()=>({useLocalize:()=> (key:string)=>key,usePrefersMobileLayout:()=>false}));
jest.mock('~/store',()=>({__esModule:true,default:{}}));
jest.mock('~/api/chatApi',()=>({getCitationUnresolvedReason:jest.fn(),getCitationDetail:jest.fn(),resolveCitationDetails:jest.fn()}));
jest.mock('~/api/chat/data-service',()=>({getFilePathApi:jest.fn()}));
jest.mock('~/pages/knowledge/FilePreview',()=>({__esModule:true,default:(props:{fileUrl:string;fileType:string;transcriptUrl?:string})=><div data-testid="host-preview">{props.fileUrl}|{props.fileType}|{props.transcriptUrl}</div>}));
const detail:ChatCitation={citationId:'tempSearch_test',type:'tempSearch',sourcePayload:{documentName:'clip.mp4',fileType:'mp4',downloadUrl:'/clip.mp4',previewUrl:'/clip.md'}};
afterEach(()=>jest.clearAllMocks());
it('passes the authorized original clip and separate transcript to the existing client file shell',async()=>{
 const view=render(<CitationDocumentPreviewContent preview={{detail}}/>);
 await waitFor(()=>expect(view.getByTestId('host-preview').textContent).toContain('/clip.mp4|mp4|'));
 expect(view.getByTestId('host-preview').textContent).toContain('/clip.md');expect(getFilePathApi).not.toHaveBeenCalled();
});
it('never mounts the client file shell for an explicitly denied source',async()=>{
 jest.mocked(getCitationUnresolvedReason).mockReturnValue('forbidden');
 const view=render(<CitationDocumentPreviewContent preview={{detail}}/>);
 await waitFor(()=>expect(view.getByText('shared:citations.com_citation.preview_unavailable')).toBeTruthy());
 expect(view.queryByTestId('host-preview')).toBeNull();expect(getFilePathApi).not.toHaveBeenCalled();
});
