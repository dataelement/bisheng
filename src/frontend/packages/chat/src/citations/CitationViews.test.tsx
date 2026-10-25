import { cleanup,fireEvent,render,waitFor } from '@testing-library/react';
import { afterEach,expect,it,vi } from 'vitest';
import { CitationDocumentPreview } from './CitationDocumentPreview';
import { CitationReferences } from './CitationReferences';
import type { CitationServices,ChatCitation } from './types';
import type { CitationFileProps } from './viewTypes';
const detail:ChatCitation={citationId:'knowledgeSearch_doc',type:'knowledgeSearch',sourcePayload:{documentName:'test.mp4',fileType:'mp4',items:[{itemId:'a',content:'cited passage'}]}};
function services():CitationServices {return {scopeKey:'A',localize:key=>key,getCitationDetail:vi.fn().mockResolvedValue(detail),resolveCitationDetails:vi.fn().mockResolvedValue([detail]),getCitationUnresolvedReason:()=>undefined,resolveDocumentUrls:vi.fn().mockResolvedValue({originalUrl:'/movie.mp4',previewUrl:'/transcript.md'}),download:vi.fn(),openArticle:vi.fn()};}
const renderFile=(props:CitationFileProps)=><div data-testid="viewer">{props.fileUrl}|{props.transcriptUrl}<button onClick={props.onDownloadFile}>download</button></div>;
afterEach(cleanup);
it('renders original media alongside its transcript and downloads the original without writes',async()=>{
 const api=services();const view=render(<CitationDocumentPreview preview={{detail}} services={api} renderFile={renderFile}/>);
 await waitFor(()=>expect(view.getByTestId('viewer').textContent).toContain('/movie.mp4|/transcript.md'));
 fireEvent.click(view.getByText('download'));expect(api.download).toHaveBeenCalledWith('/movie.mp4','test.mp4');
 expect(api.getCitationDetail).not.toHaveBeenCalled();
});
it('shows an unavailable state after a resource failure without mounting a successful viewer',async()=>{
 const api=services();vi.mocked(api.resolveDocumentUrls).mockRejectedValue(new Error('403'));
 const view=render(<CitationDocumentPreview preview={{detail}} services={api} renderFile={renderFile}/>);
 await waitFor(()=>expect(view.getByText('shared:citations.com_citation.preview_unavailable')).toBeTruthy());
 expect(view.queryByTestId('viewer')).toBeNull();
});
it('keeps local-only audit sources read-only while exposing the shared source card',async()=>{
 const api=services();const view=render(<CitationReferences content="knowledgeSearch_doc:a" citations={[detail]} services={api} renderFile={renderFile} allowRemoteResolve={false} panelOnly/>);
 await waitFor(()=>expect(view.getByRole('button',{name:/test.*\.mp4/})).toBeTruthy());
 fireEvent.click(view.getByRole('button',{name:/test.*\.mp4/}));
 await waitFor(()=>expect(view.getByTestId('viewer')).toBeTruthy());
 expect(api.getCitationDetail).not.toHaveBeenCalled();expect(api.resolveCitationDetails).not.toHaveBeenCalled();
});
it('does not mount a denied preview from a stale seed or call its file resolver',async()=>{
 const api=services();api.getCitationUnresolvedReason=()=> 'forbidden';
 const view=render(<CitationReferences content="knowledgeSearch_doc:a" citations={[detail]} services={api} renderFile={renderFile} panelOnly/>);
 await waitFor(()=>expect(view.getByText('shared:citations.com_message.source_load_failed')).toBeTruthy());
 expect(view.queryByTestId('viewer')).toBeNull();expect(api.resolveDocumentUrls).not.toHaveBeenCalled();
});
