import { useEffect, useMemo, useRef } from 'react';
import { usePreviewResource } from '@bisheng/file-viewers/resource';
import type { PreviewResource } from '@bisheng/file-viewers/types';
import { createCitationUtilities } from './preview';
import type { CitationDocumentPreviewState, CitationServices } from './types';
export function useCitationPreview(preview: CitationDocumentPreviewState | null, services: CitationServices) {
  const localizeRef=useRef(services.localize);localizeRef.current=services.localize;
  const utilities = useMemo(()=>createCitationUtilities((key,options)=>localizeRef.current(key,options)),[]);
  const detail=preview?.detail ?? null;
  const key=detail ? JSON.stringify([services.scopeKey,detail]) : '';
  const current=useRef({key,mounted:true});current.current.key=key;
  useEffect(()=>{const identity=current.current;identity.mounted=true;return()=>{identity.mounted=false;};},[]);
  const state=usePreviewResource<PreviewResource>(key,async()=>{
    const reason=detail ? services.getCitationUnresolvedReason(detail.citationId) : undefined;
    if(reason)throw Object.assign(new Error('Citation unavailable'),{reason});
    if(!detail || !utilities.isFilePreviewCitation(detail))throw new Error('Unsupported source');
    return services.resolveDocumentUrls(detail);
  });
  const resource=state.status==='ready' ? state.data : undefined;
  const isMedia=utilities.isMediaCitation(detail);
  const fileUrl=isMedia ? resource?.originalUrl || '' : resource?.previewUrl || resource?.originalUrl || '';
  const path=fileUrl.split('?')[0].split('#')[0];
  const extension=path.split('/').pop()?.match(/\.([a-zA-Z0-9]+)$/)?.[1]?.toLowerCase();
  const fileType=isMedia ? utilities.getCitationDocumentFileType(detail) : extension || utilities.getCitationDocumentFileType(detail);
  const fileName=utilities.getCitationDocumentName(detail);
  const {getCitationItemBBoxes,getCitationItem}=utilities;
  const bboxes=useMemo(()=>preview?.locateChunk && fileType==='pdf' ? getCitationItemBBoxes(detail,preview.itemIds?.length ? preview.itemIds : preview.itemId) : [],[preview?.locateChunk,preview?.itemIds,preview?.itemId,detail,fileType,getCitationItemBBoxes]);
  const chunks=useMemo(()=>preview?.locateChunk && detail ? (preview.itemIds?.length ? preview.itemIds : [preview.itemId]).map(id=>getCitationItem(detail,id)).map(item=>item?.content||item?.snippet||'').filter(Boolean) : [],[preview?.locateChunk,preview?.itemIds,preview?.itemId,detail,getCitationItem]);
  const download=async()=>{
    if(!current.current.mounted || current.current.key!==key || !resource?.originalUrl)return;
    await services.download(resource.originalUrl,fileName);
  };
  return {...state,fileName,fileType,fileUrl,transcriptUrl:isMedia ? resource?.previewUrl || '' : '',originalUrl:resource?.originalUrl || '',bboxes,targetBBox:bboxes[0]??null,chunks,download};
}
