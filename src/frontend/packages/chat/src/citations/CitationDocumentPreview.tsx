import { useRef } from 'react';
import cn from '@bisheng/ui/cn';
import { useCitationPreview } from './useCitationPreview';
import { useCitedPassageLocate } from './useCitedPassageLocate';
import type { CitationDocumentPreviewState } from './types';
import type { CitationViewProps } from './viewTypes';
interface CitationDocumentPreviewProps extends CitationViewProps {preview:CitationDocumentPreviewState|null;compactMode?:boolean;className?:string}
interface CitationPreviewBodyProps extends CitationViewProps {state:ReturnType<typeof useCitationPreview>;compactMode?:boolean;className?:string}
export function CitationPreviewBody({state,renderFile,services,compactMode=false,className}:CitationPreviewBodyProps) {
  const root=useRef<HTMLDivElement>(null);
  const locate=useCitedPassageLocate(root,state.fileUrl ? state.fileType : '',state.chunks);
  const localize=(key:string)=>services.localize('shared:citations.'+key);
  return <div className={cn('flex h-full min-h-0 flex-1 flex-col',className)}>
    {locate==='missed'&&state.chunks.length>0&&<div className="max-h-40 shrink-0 overflow-y-auto border-b border-border-base bg-orange-50 px-4 py-3 text-[13px] scrollbar-os">
      <p className="mb-1 font-medium text-orange-600">{localize('com_citation.locate_missed')}</p>
      <p className="whitespace-pre-wrap break-words border-l-2 border-border-base pl-2 text-text-2">{state.chunks.join('\n\n')}</p>
    </div>}
    <div ref={root} className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {state.fileUrl ? renderFile({fileName:state.fileName,fileType:state.fileType,fileUrl:state.fileUrl,transcriptUrl:state.transcriptUrl,highlightBboxes:state.bboxes,targetBBox:state.targetBBox,compactMode,allowDownload:!!state.originalUrl,onDownloadFile:()=>{void state.download().catch(()=>undefined);}})
        : <div className="flex h-full items-center justify-center text-[14px] text-text-3">{localize(state.status==='loading'?'com_citation.preview_loading':'com_citation.preview_unavailable')}</div>}
    </div>
  </div>;
}
export function CitationDocumentPreview({preview,services,...props}:CitationDocumentPreviewProps) {
  const state=useCitationPreview(preview,services);
  if(!preview)return null;
  return <CitationPreviewBody {...props} state={state} services={services}/>;
}
