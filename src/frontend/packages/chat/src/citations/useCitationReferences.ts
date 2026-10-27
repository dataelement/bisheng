import { useMemo, useRef } from 'react';
import { usePreviewResource } from '@bisheng/file-viewers/resource';
import { createCitationUtilities } from './preview';
import type { ChatCitation, CitationReferenceItem, CitationServices } from './types';
export type CitationReadServices=Pick<CitationServices,'scopeKey'|'localize'|'getCitationDetail'|'resolveCitationDetails'|'getCitationUnresolvedReason'>;
interface ReferenceInput {content:string;webContent?:unknown;citations?:ChatCitation[]|null;referenceItems?:CitationReferenceItem[];services:CitationReadServices;allowRemoteResolve?:boolean}
export function useCitationReferences({content,webContent,citations,referenceItems,services,allowRemoteResolve=true}:ReferenceInput) {
  const references=useMemo(()=>referenceItems?.length ? referenceItems : createCitationUtilities(services.localize).buildCitationReferenceItems({content,webContent,citations}),[content,webContent,citations,referenceItems,services.localize]);
  const utilities=createCitationUtilities(services.localize);
  const seed=utilities.createCitationDetailMap(citations);
  references.forEach(item=>{if(item.detail)seed[item.data.citationId]=item.detail;});
  const key=JSON.stringify([services.scopeKey,references.map(item=>item.data.citationId),seed,allowRemoteResolve]);
  const current=useRef(key);current.current=key;
  const requests=useRef<{key:string;pending:Map<string,Promise<ChatCitation|null>>}>({key,pending:new Map()});
  if(requests.current.key!==key)requests.current={key,pending:new Map()};
  const state=usePreviewResource<Record<string,ChatCitation>>(key,async()=>{
    const map={...seed};
    const ids=[...new Set(references.map(item=>item.data.citationId))].filter(id=>!id.startsWith('citation:')&&!services.getCitationUnresolvedReason(id)&&(!map[id]||(utilities.isFilePreviewCitation(map[id])&&!utilities.getCitationDocumentPreviewUrl(map[id]))));
    if(allowRemoteResolve&&ids.length){
      const resolved=await services.resolveCitationDetails(ids);
      resolved.forEach(item=>{map[item.citationId]=item;});
    }
    Object.keys(map).forEach(id=>{if(services.getCitationUnresolvedReason(id))delete map[id];});
    return map;
  });
  const detailMap={...(state.status==='ready'?state.data:seed)};
  const loadingMap:Record<string,boolean>={};const errorMap:Record<string,boolean>={};
  references.forEach(item=>{
    const id=item.data.citationId;const denied=services.getCitationUnresolvedReason(id);
    if(denied)delete detailMap[id];
    loadingMap[id]=state.status==='loading'&&!detailMap[id];
    errorMap[id]=!!denied || (state.status==='error'&&!detailMap[id]) || (state.status==='ready'&&!detailMap[id]&&!item.legacyPreview);
  });
  const loadCitationDetail=(id:string):Promise<ChatCitation|null>=>{
    if(services.getCitationUnresolvedReason(id))return Promise.resolve(null);
    if(!allowRemoteResolve)return Promise.resolve(detailMap[id]??null);
    const selectedKey=key;const pending=requests.current.pending;
    const existing=pending.get(id);if(existing)return existing;
    const request=services.getCitationDetail(id).then(detail=>current.current===selectedKey && !services.getCitationUnresolvedReason(id)?detail:null)
      .catch((error:unknown)=>{if(current.current!==selectedKey)return null;throw error;})
      .finally(()=>{pending.delete(id);});
    pending.set(id,request);return request;
  };
  return {references,detailMap,loadingMap,errorMap,loadCitationDetail,status:state.status};
}
