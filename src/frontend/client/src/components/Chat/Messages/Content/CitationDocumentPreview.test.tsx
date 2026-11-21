import { fireEvent,render,waitFor } from '@testing-library/react';
import { getFileDownloadApi,getFilePreviewApi } from '~/api/knowledge';
import { CitationDocumentPreviewContent } from './CitationDocumentPreviewDrawer';
import { getFilePathApi } from '~/api/chat/data-service';
import { getCitationUnresolvedReason } from '~/api/chatApi';
import type { ChatCitation } from '@bisheng/chat/citations';
jest.mock('~/hooks',()=>({useLocalize:()=> (key:string)=>key,usePrefersMobileLayout:()=>false}));
jest.mock('~/store',()=>({__esModule:true,default:{}}));
jest.mock('~/api/chatApi',()=>({getCitationUnresolvedReason:jest.fn(),getCitationDetail:jest.fn(),resolveCitationDetails:jest.fn()}));
jest.mock('~/api/chat/data-service',()=>({getFilePathApi:jest.fn()}));
jest.mock('~/api/knowledge',()=>({getFilePreviewApi:jest.fn(),getFileDownloadApi:jest.fn()}));
jest.mock('~/pages/knowledge/FilePreview',()=>({__esModule:true,default:(props:{fileUrl:string;fileType:string;transcriptUrl?:string;onDownloadFile?:()=>void})=>(
 <div data-testid="host-preview">
  {props.fileUrl}|{props.fileType}|{props.transcriptUrl}
  <button onClick={props.onDownloadFile}>Download</button>
 </div>
)}));
const detail:ChatCitation={citationId:'tempSearch_test',type:'tempSearch',sourcePayload:{documentName:'clip.mp4',fileType:'mp4',downloadUrl:'/clip.mp4',previewUrl:'/clip.md'}};
afterEach(()=>jest.resetAllMocks());
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

const knowledgeDetail: ChatCitation = {
 citationId: 'knowledgeSearch_test', type: 'knowledgeSearch',
 sourcePayload: { knowledgeId: 42, documentId: 98501, documentName: 'project.md' },
};

it('previews a visible citation without requesting download, and checks download on demand', async () => {
 jest.mocked(getFilePreviewApi).mockResolvedValue({
  original_url: '/preview/project.md', preview_url: '', html_preview_url: '',
  file_source: '', source_url: '', final_url: '', web_title: '', media_kind: '',
 });
 jest.mocked(getFileDownloadApi).mockRejectedValue(Object.assign(new Error('No permission'), { status_code: 403 }));
 const click = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
 try {
  const view = render(<CitationDocumentPreviewContent preview={{detail: knowledgeDetail}}/>);
  const preview = await view.findByTestId('host-preview');
  expect(preview.textContent).toContain('/preview/project.md|md|');
  expect(getFilePreviewApi).toHaveBeenCalledWith('42', '98501', { skip403Redirect: true, showError: false });
  expect(getFilePathApi).not.toHaveBeenCalled();
  expect(getFileDownloadApi).not.toHaveBeenCalled();
  fireEvent.click(view.getByRole('button', { name: 'Download' }));
  await waitFor(() => expect(getFileDownloadApi).toHaveBeenCalledWith('42', '98501', undefined, { skip403Redirect: true, showError: true }));
  expect(click).not.toHaveBeenCalled();
  expect(view.getByTestId('host-preview')).toBe(preview);
 } finally {
  click.mockRestore();
 }
});

it('does not fall back to the original-file endpoint when visibility denies preview', async () => {
 jest.mocked(getFilePreviewApi).mockRejectedValue(Object.assign(new Error('No permission'), { status_code: 403 }));
 const view = render(<CitationDocumentPreviewContent preview={{detail: knowledgeDetail}}/>);
 await view.findByText('shared:citations.com_citation.preview_unavailable');
 expect(view.queryByTestId('host-preview')).toBeNull();
 expect(getFilePathApi).not.toHaveBeenCalled();
 expect(getFileDownloadApi).not.toHaveBeenCalled();
});
