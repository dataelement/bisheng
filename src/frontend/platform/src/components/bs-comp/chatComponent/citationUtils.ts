import i18next from 'i18next';
import { createCitationUtilities } from '@bisheng/chat/citations';
export * from '@bisheng/chat/citations';
const utilities=createCitationUtilities((key,options)=>String(i18next.t(key,options)));
export const { buildCitationPreview, getLegacyCitationPreview, getCitationArticleUrl, isArticleCitation, isFilePreviewCitation, normalizeCitationType, getCitationSourceLabelKey, createCitationDetailMap, isRagCitation, isTempCitation, getCitationDocumentName, getCitationDocumentFileType, getCitationItem, getCitationItemBBoxes, parseCitationBBoxes, formatCitationWebDate, formatCitationLocation, getCitationDocumentPreviewUrl, getCitationDocumentDownloadUrl, isRagCitationMissingPreviewUrl, isMediaCitation, buildCitationDocumentPreview, buildCitationReferenceItems }=utilities;
// Platform historically exposes the downloadable original via this alias.
export const getCitationDocumentUrl=utilities.getCitationDocumentDownloadUrl;
export const getCitationSourceLabel=(type?:string)=>String(i18next.t(utilities.getCitationSourceLabelKey(type)));
export function getCitationClassName(type?:string){return utilities.normalizeCitationType(type)==='web'?'bg-[#F7F3FF] text-[#7224D9]':'bg-[#F5F8FF] text-[#024DE3]';}
export function toAbsolutePreviewUrl(url?:string|null){
  if(!url)return '';if(/^https?:\/\//i.test(url))return url;
  if(url.startsWith('/'))return `${window.location.origin}${url}`;
  return `${window.location.origin}${__APP_ENV__.BASE_URL}/${url.replace(/^\/+/,'')}`;
}
