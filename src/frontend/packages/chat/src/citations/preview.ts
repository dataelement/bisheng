import { createReferenceUtilities } from './referenceItems';
import { createExportUtilities } from './export';
import { asRecord } from '../core/normalizeHistory';
import type { ChatCitation, ChatCitationPayload, CitationDisplayData, CitationPreview, CitationPdfBBox, ChatLocalize } from './types';
export function createCitationUtilities(localize: ChatLocalize) {
function buildCitationPreview(detail: ChatCitation | null, data: Partial<CitationDisplayData>): CitationPreview | null {
    if (!detail?.sourcePayload) {
        return null;
    }
    const payload = detail.sourcePayload;
    const item = getCitationItem(detail, data.itemId);
    const type = normalizeCitationType(detail.type || data.type);
    if (type === 'article') {
        return {
            title: payload.title || `${data.label ?? ''}`,
            snippet: item?.snippet || payload.snippet || '',
            sourceName: payload.title || payload.sourceUrl || '',
            sourceMeta: '',
            link: payload.sourceUrl,
            type,
        };
    }
    if (type === 'web') {
        return {
            title: item?.title || payload.title || payload.url || localize('shared:app_chat.citation.untitled', { index: data.label ?? '' }),
            snippet: extractWebSnippetContent(item?.snippet || payload.snippet),
            sourceName: payload.source || payload.url || localize('shared:app_chat.source_web'),
            sourceMeta: formatCitationWebDate(payload.datePublished || ''),
            link: payload.url || payload.sourceUrl,
            type,
        };
    }
    if (type === 'temp') {
        return {
            title: getCitationDocumentName(detail) || localize('shared:app_chat.citation.untitled', { index: data.label ?? '' }),
            snippet: extractRagParagraphContent(item?.content || item?.snippet || payload.snippet),
            sourceName: localize('shared:app_chat.citation.source_temp_kb'),
            sourceMeta: formatCitationLocation(detail, data.itemId),
            link: payload.previewUrl || payload.downloadUrl || payload.sourceUrl,
            type,
        };
    }
    return {
        title: getCitationDocumentName(detail) || localize('shared:app_chat.citation.untitled', { index: data.label ?? '' }),
        snippet: extractRagParagraphContent(item?.content || item?.snippet || payload.snippet),
        sourceName: payload.knowledgeName || payload.fileType || localize('shared:app_chat.source_document'),
        sourceMeta: formatCitationLocation(detail, data.itemId),
        link: payload.downloadUrl,
        type,
    };
}
function getCitationItem(detail: ChatCitation | null, itemId?: string) {
    const items = detail?.sourcePayload?.items;
    if (!items?.length) {
        return null;
    }
    return items.find((item) => item.itemId === itemId || item.chunkId === itemId) ?? items[0];
}
function normalizeCitationType(type?: string) {
    const normalizedType = type?.toLowerCase();
    if (normalizedType === 'web' || normalizedType === 'websearch') {
        return 'web';
    }
    if (normalizedType === 'article' || normalizedType === 'articlesearch') {
        return 'article';
    }
    if (normalizedType === 'temp' || normalizedType === 'tempsearch') {
        return 'temp';
    }
    return 'rag';
}
function extractWebSnippetContent(value?: string | null) {
    return value || '';
}
function formatCitationWebDate(value?: string | null) {
    const rawValue = String(value || '').trim();
    if (!rawValue) {
        return '';
    }
    const normalizedValue = rawValue.replace(/\//g, '-');
    const parsedDate = new Date(normalizedValue);
    if (Number.isNaN(parsedDate.getTime())) {
        return rawValue;
    }
    return `${parsedDate.getFullYear()}-${padTimeUnit(parsedDate.getMonth() + 1)}-${padTimeUnit(parsedDate.getDate())} ${padTimeUnit(parsedDate.getHours())}:${padTimeUnit(parsedDate.getMinutes())}`;
}
function padTimeUnit(value: number) {
    return String(value).padStart(2, '0');
}
function getCitationDocumentName(detail?: ChatCitation | null) {
    const payload = detail?.sourcePayload;
    const firstItem = payload?.items?.[0];
    const candidates = [
        payload?.documentName,
        payload?.fileName,
        payload?.filename,
        payload?.file_name,
        firstItem?.documentName,
        firstItem?.fileName,
        firstItem?.filename,
        firstItem?.file_name,
        firstItem?.title,
        payload?.title,
        payload?.knowledgeName,
    ];
    const normalized = candidates
        .map((item) => String(item || '').trim())
        .filter(Boolean)
        .filter((item) => !/^(new chat|新对话)$/i.test(item));
    return normalized[0] || localize('shared:app_chat.document_preview');
}
function extractRagParagraphContent(value?: string | null) {
    return extractTaggedContent(value, 'paragraph_content');
}
function extractTaggedContent(value?: string | null, tagName?: string) {
    if (!value || !tagName) {
        return '';
    }
    const pattern = new RegExp(`<${tagName}>([\\s\\S]*?)<\\/${tagName}>`, 'i');
    return value.match(pattern)?.[1]?.trim() || value;
}
function formatCitationLocation(detail: ChatCitation | null, itemId?: string) {
    const payload = detail?.sourcePayload;
    const item = getCitationItem(detail, itemId);
    const page = Number(item?.page ?? payload?.page);
    if (Number.isFinite(page)) {
        if (parseCitationBBoxes(item?.bbox).length) {
            if (page >= 0)
                return localize('shared:app_chat.page', { 0: page + 1 });
        }
        else if (page > 0) {
            return localize('shared:app_chat.page', { 0: page });
        }
    }
    const chunkIndex = Number(item?.chunkIndex);
    if (item?.chunkIndex != null && Number.isFinite(chunkIndex) && chunkIndex >= 0) {
        return localize('shared:app_chat.chunk', { 0: chunkIndex + 1 });
    }
    return '';
}
function parseCitationBBoxes(rawBBox?: string | null): CitationPdfBBox[] {
    if (!rawBBox) {
        return [];
    }
    try {
        const parsed = asRecord(JSON.parse(rawBBox) as unknown);
        const chunkBBoxes: unknown[] = Array.isArray(parsed?.chunk_bboxes) ? parsed.chunk_bboxes : [];
        return chunkBBoxes
            .map(value => { const item = asRecord(value); return { page: Number(item.page), bbox: item.bbox }; })
            .filter((item): item is CitationPdfBBox => Number.isFinite(item.page) && isValidBBox(item.bbox));
    }
    catch {
        return [];
    }
}
function isValidBBox(value: unknown): value is [
    number,
    number,
    number,
    number
] {
    return Array.isArray(value)
        && value.length === 4
        && value.every((item) => typeof item === 'number' && Number.isFinite(item));
}
function getLegacyCitationPreview(webContent: unknown, label?: number): CitationPreview | null {
    if (!label) {
        return null;
    }
    const raw = Array.isArray(webContent) ? webContent[label - 1] : null;
    const item = raw && typeof raw === 'object' ? raw as ChatCitationPayload : null;
    if (!item) {
        return null;
    }
    return {
        title: item.title || item.url || localize('shared:app_chat.citation.untitled', { index: label }),
        snippet: item.snippet || item.content || '',
        sourceName: item.source || item.url || localize('shared:app_chat.source_web'),
        sourceMeta: formatCitationWebDate(item.datePublished || item.date || ''),
        link: item.url,
        type: 'web',
    };
}
function getCitationDocumentUrl(detail?: ChatCitation | null) {
    if (getCitationKnowledgeFileId(detail) != null)
        return '';
    return getCitationDocumentPreviewUrl(detail);
}
function getCitationKnowledgeFileId(detail?: ChatCitation | null): number | null {
    const documentId = detail?.sourcePayload?.documentId;
    if (typeof documentId === 'number' && Number.isFinite(documentId))
        return documentId;
    if (typeof documentId === 'string' && documentId.trim() !== '' && Number.isFinite(Number(documentId))) {
        return Number(documentId);
    }
    return null;
}
function getCitationDocumentPreviewUrl(detail?: ChatCitation | null) {
    const payload = detail?.sourcePayload;
    const signedUrl = payload?.previewUrl || payload?.downloadUrl || '';
    if (signedUrl) {
        return signedUrl;
    }
    return isTempCitation(detail) ? payload?.sourceUrl || '' : '';
}
function isTempCitation(detail?: ChatCitation | null, type?: string) {
    return normalizeCitationType(detail?.type || type) === 'temp';
}
function getCitationArticleUrl(detail?: ChatCitation | null) {
    return detail?.sourcePayload?.sourceUrl || '';
}
function isArticleCitation(detail?: ChatCitation | null, type?: string) {
    return normalizeCitationType(detail?.type || type) === 'article';
}
function isFilePreviewCitation(detail?: ChatCitation | null, type?: string) {
    const normalizedType = normalizeCitationType(detail?.type || type);
    return normalizedType === 'rag' || normalizedType === 'temp';
}
function getCitationSourceLabelKey(type?: string) {
    const normalizedType = normalizeCitationType(type);
    if (normalizedType === 'web')
        return 'shared:app_chat.citation.source_web';
    if (normalizedType === 'article')
        return 'shared:app_chat.citation.source_article';
    if (normalizedType === 'temp')
        return 'shared:app_chat.citation.source_temp_kb';
    return 'shared:app_chat.citation.source_document';
}
function createCitationDetailMap(citations?: ChatCitation[] | null) {
    return (citations ?? []).reduce<Record<string, ChatCitation>>((acc, item) => {
        if (item?.citationId) {
            acc[item.citationId] = item;
        }
        return acc;
    }, {});
}
function isRagCitation(detail?: ChatCitation | null, type?: string) {
    return normalizeCitationType(detail?.type || type) === 'rag';
}

function getCitationDocumentFileType(detail?: ChatCitation | null) {
  const payload = detail?.sourcePayload;
  const fileType = payload?.fileType || getCitationDocumentName(detail).split('.').pop() || '';
  return String(fileType).toLowerCase();
}

function getCitationItemBBoxes(detail: ChatCitation | null, itemId?: string | string[]) {
  const items = detail?.sourcePayload?.items;
  if (!items?.length) {
    return [];
  }

  const requestedIds = (Array.isArray(itemId) ? itemId : itemId ? [itemId] : [])
    .map((id) => String(id))
    .filter(Boolean);
  const matched = requestedIds.length
    ? items.filter(
        (item) => requestedIds.includes(String(item.itemId)) || requestedIds.includes(String(item.chunkId)),
      )
    : [];
  const selected = matched.length ? matched : [items[0]];

  const seen = new Set<string>();
  const bboxes: CitationPdfBBox[] = [];
  for (const item of selected) {
    for (const box of parseCitationBBoxes(item?.bbox)) {
      const key = `${box.page}:${box.bbox.map((value) => value.toFixed(2)).join(',')}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      bboxes.push(box);
    }
  }
  return bboxes;
}

function buildCitationDocumentPreview(detail: ChatCitation | null, data: Partial<CitationDisplayData>): CitationPreview | null {
  if (!detail?.sourcePayload) {
    return null;
  }

  const payload = detail.sourcePayload;
  const type = normalizeCitationType(detail.type || data.type);

  if (type === 'article') {
    return {
      title: payload.title || `${data.label ?? ''}`,
      snippet: payload.snippet || '',
      sourceName: payload.title || payload.sourceUrl || '',
      sourceMeta: '',
      link: payload.sourceUrl,
      type,
    };
  }

  if (type === 'web') {
    return {
      title: payload.title || payload.url || localize('shared:app_chat.citation.untitled', { index: data.label ?? '' }),
      snippet: '',
      sourceName: payload.source || payload.url || localize('shared:app_chat.source_web'),
      sourceMeta: formatCitationWebDate(payload.datePublished || ''),
      link: payload.url || payload.sourceUrl,
      type,
    };
  }

  if (type === 'temp') {
    return {
      title: getCitationDocumentName(detail) || localize('shared:app_chat.citation.untitled', { index: data.label ?? '' }),
      snippet: '',
      sourceName: localize('shared:app_chat.citation.source_temp_kb'),
      sourceMeta: payload.fileType || '',
      link: payload.previewUrl || payload.downloadUrl || payload.sourceUrl,
      type,
    };
  }

  return {
    title: getCitationDocumentName(detail) || localize('shared:app_chat.citation.untitled', { index: data.label ?? '' }),
    snippet: '',
    sourceName: payload.knowledgeName || payload.fileType || localize('shared:app_chat.source_document'),
    sourceMeta: payload.fileType || '',
    link: payload.downloadUrl,
    type,
  };
}

function getCitationDocumentDownloadUrl(detail?: ChatCitation | null) {
  return detail?.sourcePayload?.downloadUrl || (isTempCitation(detail) ? detail?.sourcePayload?.sourceUrl || '' : '');
}
function isRagCitationMissingPreviewUrl(detail?: ChatCitation | null) {
  return !!detail?.citationId && isFilePreviewCitation(detail) && !(detail.sourcePayload?.previewUrl || detail.sourcePayload?.downloadUrl);
}
function isMediaCitation(detail?: ChatCitation | null) {
  return new Set(['mp3','wav','m4a','aac','flac','ogg','mp4','mov','avi','mkv','webm']).has(getCitationDocumentFileType(detail));
}
return { buildCitationPreview, getLegacyCitationPreview, getCitationDocumentUrl, getCitationArticleUrl, isArticleCitation, isFilePreviewCitation, normalizeCitationType, getCitationSourceLabelKey, createCitationDetailMap, isRagCitation, isTempCitation, getCitationDocumentName, getCitationDocumentFileType, getCitationItem, getCitationItemBBoxes, parseCitationBBoxes, formatCitationWebDate, formatCitationLocation, getCitationKnowledgeFileId, getCitationDocumentPreviewUrl, getCitationDocumentDownloadUrl, isRagCitationMissingPreviewUrl, isMediaCitation, buildCitationDocumentPreview, ...createReferenceUtilities({createCitationDetailMap,getLegacyCitationPreview}), ...createExportUtilities({normalizeCitationType,getCitationDocumentName,getCitationItem,formatCitationLocation}) };
}
