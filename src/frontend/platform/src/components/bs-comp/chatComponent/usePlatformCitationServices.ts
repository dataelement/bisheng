import type { CitationServices } from '@bisheng/chat/citations';
import { createCitationUtilities } from '@bisheng/chat/citations';
import { useTranslation } from 'react-i18next';
import { getCitationDetail,getCitationUnresolvedReason,resolveCitationDetails } from '@/controllers/API';
import { getCitationAccessScope } from '@/controllers/citationScope';
import { toAbsolutePreviewUrl } from './citationUtils';
export function usePlatformCitationServices():CitationServices {
 const {t}=useTranslation(['bs','shared']);const localize=(key:string,options?:Record<string,unknown>)=>String(t(key,options));
 return {scopeKey:getCitationAccessScope(),localize,getCitationDetail,getCitationUnresolvedReason,resolveCitationDetails,
  resolveDocumentUrls:async detail=>{
   const utilities=createCitationUtilities(localize);
   const reason=getCitationUnresolvedReason(detail.citationId);if(reason)throw Object.assign(new Error('Citation unavailable'),{reason});
   const registryBacked=!detail.citationId.startsWith('citation:');
   const needsFreshUrl=utilities.isRagCitation(detail)||!utilities.getCitationDocumentPreviewUrl(detail);
   const effective=registryBacked&&needsFreshUrl ? await getCitationDetail(detail.citationId,{fresh:true}) : detail;
   return {originalUrl:toAbsolutePreviewUrl(utilities.getCitationDocumentDownloadUrl(effective)),previewUrl:toAbsolutePreviewUrl(utilities.getCitationDocumentPreviewUrl(effective))};
  },
  download:(url,fileName)=>{const link=document.createElement('a');link.href=url;link.download=fileName;link.target='_blank';link.rel='noopener';document.body.appendChild(link);link.click();link.remove();},
  openArticle:url=>{window.open(url,'_blank','noopener,noreferrer');},
 };
}
