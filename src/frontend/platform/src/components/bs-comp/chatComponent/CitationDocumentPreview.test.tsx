import { render,waitFor } from '@testing-library/react';
import { afterEach,expect,it,vi } from 'vitest';
import { CitationDocumentPreviewContent } from './CitationDocumentPreviewDrawer';
import type { ChatCitation } from '@bisheng/chat/citations';
const { reason }=vi.hoisted(()=>({reason:vi.fn()}));
vi.mock('@/controllers/API',()=>({getCitationDetail:vi.fn(),resolveCitationDetails:vi.fn(),getCitationUnresolvedReason:reason}));
const detail:ChatCitation={citationId:'knowledgeSearch_fixture',type:'knowledgeSearch',sourcePayload:{documentName:'note.txt',downloadUrl:'https://storage.example/files/note.txt',previewUrl:'https://storage.example/files/note.txt'}};
afterEach(()=>{vi.unstubAllGlobals();reason.mockReset();});
it('uses the shared text viewer and preserves the platform file-proxy policy',async()=>{
 const fetch=vi.fn().mockResolvedValue({ok:true,text:async()=> 'Shared preview fixture text'});vi.stubGlobal('fetch',fetch);
 const view=render(<CitationDocumentPreviewContent preview={{detail}}/>);
 await waitFor(()=>expect(view.getByText('Shared preview fixture text')).toBeTruthy());
 expect(fetch.mock.calls[0][0]).toBe('/files/note.txt');
});
it('does not fetch a stale seeded file after an explicit citation denial',async()=>{
 reason.mockReturnValue('forbidden');const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
 const view=render(<CitationDocumentPreviewContent preview={{detail}}/>);
 await waitFor(()=>expect(view.getByText('shared:citations.com_citation.preview_unavailable')).toBeTruthy());
 expect(fetch).not.toHaveBeenCalled();
});
