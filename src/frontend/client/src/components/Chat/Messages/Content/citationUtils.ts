import i18next from 'i18next';
import { createCitationUtilities, createCitationResourceResolver } from '@bisheng/chat/citations';
import type { ChatCitation } from '~/api/chatApi';
import { getFilePathApi } from '~/api/chat/data-service';
import { getCitationAccessScope } from '~/api/citationScope';
export * from '@bisheng/chat/citations';
const legacyKeys: Record<string,string> = {
 'shared:app_chat.page':'com_linsight_export_page', 'shared:app_chat.chunk':'com_linsight_export_chunk',
 'shared:app_chat.document_preview':'com_message.document_preview',
 'shared:app_chat.source_web':'com_message.source_name_fallback_web',
 'shared:app_chat.source_document':'com_message.source_name_fallback_document',
 'shared:app_chat.citation.untitled':'com_citation.untitled',
 'shared:app_chat.citation.source_temp_kb':'com_citation.source_temp_kb',
};
const translate = i18next.t as unknown as (key: string, options?: Record<string, unknown>) => string;
const utilities = createCitationUtilities((key, options) => translate(legacyKeys[key] || key, options));
export const { buildCitationPreview, getLegacyCitationPreview, getCitationDocumentUrl, getCitationArticleUrl, isArticleCitation, isFilePreviewCitation, normalizeCitationType, getCitationSourceLabelKey, createCitationDetailMap, isRagCitation, isTempCitation, getCitationDocumentName, getCitationDocumentFileType, getCitationItem, getCitationItemBBoxes, parseCitationBBoxes, formatCitationWebDate, formatCitationLocation, getCitationDocumentPreviewUrl, isMediaCitation, buildCitationDocumentPreview, buildCitationReferenceItems, stripCitationMarkers, stripCitationHandles, bakeCitationsForExport } = utilities;
const resolveResource = createCitationResourceResolver(async id => {
  const response: unknown = await getFilePathApi(id);
  const envelope = response && typeof response === 'object' ? response as Record<string,unknown> : {};
  const candidate = envelope.data ?? envelope;
  const data = candidate && typeof candidate === 'object' ? candidate as Record<string,unknown> : {};
  return { originalUrl: typeof data.original_url === 'string' ? data.original_url : '', previewUrl: typeof data.preview_url === 'string' ? data.preview_url : '' };
});
export function resolveCitationDocumentUrls(detail?: ChatCitation | null) { return resolveResource(detail,getCitationAccessScope()); }
export async function resolveCitationDocumentUrl(detail?: ChatCitation | null) {const resource=await resolveCitationDocumentUrls(detail);return resource.previewUrl || resource.originalUrl;}
export async function resolveCitationDownloadUrl(detail?: ChatCitation | null) {const resource=await resolveCitationDocumentUrls(detail);return resource.originalUrl;}
export function toAbsolutePreviewUrl(url?: string | null) {
  if(!url)return '';
  if(/^https?:\/\//i.test(url))return url;
  if(url.startsWith('/'))return `${window.location.origin}${url}`;
  return `${window.location.origin}${__APP_ENV__.BASE_URL}/${url.replace(/^\/+/,'')}`;
}
