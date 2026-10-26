import { act,cleanup,fireEvent,render } from '@testing-library/react';
import { afterEach,expect,it,vi } from 'vitest';
import type { ChatCitation } from './types';
import { InlineCitation } from './inline';
afterEach(cleanup);
it('does not reopen a preview after its citation unmounts during detail loading',async()=>{
 let finish!:(detail:ChatCitation)=>void;const load=vi.fn(()=>new Promise<ChatCitation>(resolve=>{finish=resolve;}));const onOpen=vi.fn();
 const view=render(<InlineCitation presentation={{localize:key=>key}} data={{citationId:'knowledgeSearch_A',itemId:'a',ref:'knowledgeSearch_A:a',type:'knowledgeSearch',label:1}} loadCitationDetail={load} popoverKey="a" activePopoverKey={null} onActivePopoverKeyChange={()=>undefined} onClosePopover={()=>undefined} onOpenDocumentPreview={onOpen} citationPreviewUsesHover>1</InlineCitation>);
 fireEvent.click(view.getByText('1'));expect(load).toHaveBeenCalledTimes(1);view.unmount();
 await act(async()=>finish({citationId:'knowledgeSearch_A',type:'knowledgeSearch',sourcePayload:{downloadUrl:'/A.pdf'}}));
 expect(onOpen).not.toHaveBeenCalled();
});
