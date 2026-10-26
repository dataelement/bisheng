import type { CitationServices } from '@bisheng/chat/citations';
import { getCitationDetail,getCitationUnresolvedReason,resolveCitationDetails } from '~/api/chatApi';
import { getCitationAccessScope } from '~/api/citationScope';
import { useLocalize } from '~/hooks';
import { resolveCitationDocumentUrls,toAbsolutePreviewUrl } from './citationUtils';
export function useClientCitationServices():CitationServices {
  const localize=useLocalize();
  return {scopeKey:getCitationAccessScope(),localize,getCitationDetail,getCitationUnresolvedReason,resolveCitationDetails,
    resolveDocumentUrls:async detail=>{const urls=await resolveCitationDocumentUrls(detail);return {originalUrl:toAbsolutePreviewUrl(urls.originalUrl),previewUrl:toAbsolutePreviewUrl(urls.previewUrl)};},
    download:(url,fileName)=>{const link=document.createElement('a');link.href=url;link.download=fileName;link.target='_blank';link.rel='noopener';document.body.appendChild(link);link.click();link.remove();},
    openArticle:url=>{window.open(url,'_blank','noopener,noreferrer');},
  };
}
