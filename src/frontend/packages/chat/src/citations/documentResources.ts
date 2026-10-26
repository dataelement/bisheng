import type { PreviewResource } from '@bisheng/file-viewers/types';
import type { ChatCitation } from './types';
/** Each host owns a resolver; only pending requests in the same access scope are reused. */
export function createCitationResourceResolver(readKnowledgeFile: (id: string) => Promise<PreviewResource>) {
  const pending=new Map<string,Promise<PreviewResource>>();
  return (detail:ChatCitation|null|undefined,scopeKey:string):Promise<PreviewResource> => {
    const payload=detail?.sourcePayload;
    const temporary=/^temp(?:search)?$/i.test(detail?.type||'');
    const id=payload?.documentId;
    if(!temporary && id!==undefined && String(id).trim()!=='' && Number.isFinite(Number(id))) {
      const key=JSON.stringify([scopeKey,String(id)]);
      const existing=pending.get(key);if(existing)return existing;
      const request=readKnowledgeFile(String(id)).finally(()=>{if(pending.get(key)===request)pending.delete(key);});
      pending.set(key,request);return request;
    }
    const originalUrl=payload?.downloadUrl||(temporary?payload?.sourceUrl:'')||'';
    const previewUrl=payload?.previewUrl||originalUrl;
    return Promise.resolve({originalUrl,previewUrl});
  };
}
