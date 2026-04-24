import type { ChatCitation } from '~/api/chatApi';
import { getFilePreviewApi } from '~/api/knowledge';

export type CitationDisplayData = {
  label: number;
  ref: string;
  type: string;
  groupKey: string;
  chunkId: string;
  citationId: string;
  itemId: string;
};

export type CitationPreview = {
  title: string;
  snippet: string;
  sourceName: string;
  sourceMeta: string;
  link?: string;
  type: string;
};

export type CitationReferenceItem = {
  key: string;
  data: CitationDisplayData;
  detail?: ChatCitation | null;
  legacyPreview?: CitationPreview | null;
};

export type CitationPdfBBox = {
  page: number;
  bbox: [number, number, number, number];
};

export type CitationDetailLoader = (citationId: string) => Promise<ChatCitation | null>;

export const CITATION_START = '\ue200';
export const CITATION_SEPARATOR = '\ue201';
export const CITATION_END = '\ue202';

export function normalizeCitationMarkers(content: string) {
  return content
    .replace(/\\u[eE]200/g, CITATION_START)
    .replace(/\\u[eE]201/g, CITATION_SEPARATOR)
    .replace(/\\u[eE]202/g, CITATION_END);
}

function padTimeUnit(value: number) {
  return String(value).padStart(2, '0');
}

export function formatCitationWebDate(value?: string | null) {
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

function parseCitationRef(ref: string) {
  const lastColonIndex = ref.lastIndexOf(':');
  if (lastColonIndex < 0) {
    return null;
  }

  const citationId = ref.slice(0, lastColonIndex).trim();
  const itemId = ref.slice(lastColonIndex + 1).trim();

  if (!citationId || !itemId) {
    return null;
  }

  const firstUnderscoreIndex = citationId.indexOf('_');
  if (firstUnderscoreIndex < 0) {
    return null;
  }

  const type = citationId.slice(0, firstUnderscoreIndex).trim();
  const groupKey = citationId.slice(firstUnderscoreIndex + 1).trim();

  if (!type || !groupKey) {
    return null;
  }

  return {
    type,
    groupKey,
    chunkId: itemId,
    citationId,
    itemId,
  };
}

export function buildCitationDisplayData(ref: string): CitationDisplayData | null {
  const parsedRef = parseCitationRef(ref);
  if (!parsedRef) {
    return null;
  }

  const { citationId, itemId, type, groupKey, chunkId } = parsedRef;

  return {
    label: 0,
    ref,
    type,
    groupKey,
    chunkId,
    citationId,
    itemId,
  };
}

export function transformPrivateCitations(content: string) {
  const normalizedCitationContent = normalizeCitationMarkers(content);

  if (!normalizedCitationContent.includes(CITATION_START)) {
    return { transformedContent: normalizedCitationContent, citationMap: {} as Record<string, CitationDisplayData> };
  }

  const citationMap: Record<string, CitationDisplayData> = {};
  const groupIndexMap: Record<string, number> = {};
  let nextGroupLabel = 1;
  const buildCitationPlaceholder = (ref: string) => {
    const normalizedRef = ref.trim();
    if (!normalizedRef) {
      return '';
    }

    if (!citationMap[normalizedRef]) {
      const displayData = buildCitationDisplayData(normalizedRef);
      if (displayData) {
        const groupId = `${displayData.type}_${displayData.groupKey}_${displayData.itemId}`;
        if (!groupIndexMap[groupId]) {
          groupIndexMap[groupId] = nextGroupLabel;
          nextGroupLabel += 1;
        }
        displayData.label = groupIndexMap[groupId];
        citationMap[normalizedRef] = displayData;
      }
    }

    return citationMap[normalizedRef] ? `[citationref:${normalizedRef}]` : '';
  };

  let transformedContent = '';
  let currentRef = '';
  let isInsideCitation = false;

  for (const char of normalizedCitationContent) {
    if (!isInsideCitation) {
      if (char === CITATION_START) {
        isInsideCitation = true;
        currentRef = '';
        continue;
      }
      transformedContent += char;
      continue;
    }

    if (char === CITATION_SEPARATOR) {
      transformedContent += buildCitationPlaceholder(currentRef);
      currentRef = '';
      continue;
    }

    if (char === CITATION_END) {
      transformedContent += buildCitationPlaceholder(currentRef);
      currentRef = '';
      isInsideCitation = false;
      continue;
    }

    currentRef += char;
  }

  return { transformedContent, citationMap };
}

export function getCitationClassName(type?: string) {
  switch (type?.toLowerCase()) {
    case 'web':
    case 'websearch':
      return 'bg-[#F3EEFF] text-[#7C3AED] hover:bg-[#E9DFFF]';
    case 'knowledgesearch':
      return 'bg-[#EEF3FF] text-[#1D4ED8] hover:bg-[#E3ECFF]';
    default:
      return 'bg-[#F2F3F5] text-[#4E5969] hover:bg-[#E5E6EB]';
  }
}

export function normalizeCitationType(type?: string) {
  const normalizedType = type?.toLowerCase();
  if (normalizedType === 'web' || normalizedType === 'websearch') {
    return 'web';
  }
  return 'rag';
}

export function isRagCitation(detail?: ChatCitation | null, type?: string) {
  return normalizeCitationType(detail?.type || type) === 'rag';
}

export function getCitationSourceLabel(type?: string) {
  return normalizeCitationType(type) === 'web' ? '网页' : '文档';
}

export function getCitationItem(detail: ChatCitation | null, itemId?: string) {
  const items = detail?.sourcePayload?.items;
  if (!items?.length) {
    return null;
  }

  return items.find((item) => item.itemId === itemId || item.chunkId === itemId) ?? items[0];
}

export function getCitationDocumentName(detail?: ChatCitation | null) {
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
    // Avoid using chat-session titles as document names.
    .filter((item) => !/^(new chat|新对话)$/i.test(item));

  return normalized[0] || '文档预览';
}

export function getCitationDocumentFileType(detail?: ChatCitation | null) {
  const payload = detail?.sourcePayload;
  const fileType = payload?.fileType || getCitationDocumentName(detail).split('.').pop() || '';
  return String(fileType).toLowerCase();
}

export function getCitationDocumentUrl(detail?: ChatCitation | null) {
  const payload = detail?.sourcePayload;
  return payload?.previewUrl || payload?.downloadUrl || '';
}

function parseOptionalId(value: unknown) {
  if (value === null || value === undefined || value === '') {
    return '';
  }
  const normalized = String(value).trim();
  return normalized || '';
}

function getCitationKnowledgeId(detail?: ChatCitation | null) {
  const payload = detail?.sourcePayload;
  return parseOptionalId(
    payload?.knowledgeId
    ?? payload?.knowledge_id
    ?? payload?.spaceId
    ?? payload?.space_id,
  );
}

function getCitationDocumentId(detail?: ChatCitation | null) {
  const payload = detail?.sourcePayload;
  return parseOptionalId(
    payload?.documentId
    ?? payload?.document_id
    ?? payload?.fileId
    ?? payload?.file_id,
  );
}

const citationDocumentUrlRequestCache: Record<string, Promise<string>> = {};

export async function resolveCitationDocumentUrl(detail?: ChatCitation | null) {
  const directUrl = getCitationDocumentUrl(detail);
  if (directUrl) {
    return directUrl;
  }

  const knowledgeId = getCitationKnowledgeId(detail);
  const documentId = getCitationDocumentId(detail);
  if (!knowledgeId || !documentId) {
    return '';
  }

  const cacheKey = `${knowledgeId}:${documentId}`;
  if (!citationDocumentUrlRequestCache[cacheKey]) {
    citationDocumentUrlRequestCache[cacheKey] = getFilePreviewApi(knowledgeId, documentId)
      .then((data) => data.preview_url || data.original_url || '')
      .catch(() => '')
      .finally(() => {
        delete citationDocumentUrlRequestCache[cacheKey];
      });
  }

  return citationDocumentUrlRequestCache[cacheKey];
}

export function toAbsolutePreviewUrl(url?: string | null) {
  if (!url) {
    return '';
  }

  if (/^https?:\/\//i.test(url)) {
    return url;
  }

  if (url.startsWith('/')) {
    return `${window.location.origin}${url}`;
  }

  return `${window.location.origin}${__APP_ENV__.BASE_URL}/${url.replace(/^\/+/, '')}`;
}

function isValidBBox(value: unknown): value is [number, number, number, number] {
  return Array.isArray(value)
    && value.length === 4
    && value.every((item) => typeof item === 'number' && Number.isFinite(item));
}

export function parseCitationBBoxes(rawBBox?: string | null): CitationPdfBBox[] {
  if (!rawBBox) {
    return [];
  }

  try {
    const parsed = JSON.parse(rawBBox);
    const chunkBBoxes = Array.isArray(parsed?.chunk_bboxes) ? parsed.chunk_bboxes : [];
    return chunkBBoxes
      .map((item: any) => ({
        page: Number(item?.page),
        bbox: item?.bbox,
      }))
      .filter((item): item is CitationPdfBBox => Number.isFinite(item.page) && isValidBBox(item.bbox));
  } catch {
    return [];
  }
}

export function getCitationItemBBoxes(detail: ChatCitation | null, itemId?: string) {
  const item = getCitationItem(detail, itemId);
  return parseCitationBBoxes(item?.bbox);
}

export function getLegacyCitationPreview(webContent: any, label?: number): CitationPreview | null {
  if (!label) {
    return null;
  }

  const item = webContent?.[label - 1];
  if (!item) {
    return null;
  }

  return {
    title: item.title || item.url || `引用 ${label}`,
    snippet: item.snippet || item.content || '',
    sourceName: item.source || item.url || '网页',
    sourceMeta: formatCitationWebDate(item.datePublished || item.date || ''),
    link: item.url,
    type: 'web',
  };
}

function extractTaggedContent(value?: string | null, tagName?: string) {
  if (!value || !tagName) {
    return '';
  }

  const pattern = new RegExp(`<${tagName}>([\\s\\S]*?)<\\/${tagName}>`, 'i');
  return value.match(pattern)?.[1]?.trim() || value;
}

function extractRagParagraphContent(value?: string | null) {
  return extractTaggedContent(value, 'paragraph_content');
}

function extractWebSnippetContent(value?: string | null) {
  return value || '';
}

export function buildCitationPreview(detail: ChatCitation | null, data: Partial<CitationDisplayData>): CitationPreview | null {
  if (!detail?.sourcePayload) {
    return null;
  }

  const payload = detail.sourcePayload;
  const item = getCitationItem(detail, data.itemId);
  const type = normalizeCitationType(detail.type || data.type);

  if (type === 'web') {
    return {
      title: item?.title || payload.title || payload.url || `引用 ${data.label ?? ''}`,
      snippet: extractWebSnippetContent(item?.snippet || payload.snippet),
      sourceName: payload.source || payload.url || '网页',
      sourceMeta: formatCitationWebDate(payload.datePublished || ''),
      link: payload.url || payload.sourceUrl,
      type,
    };
  }

  return {
    title: getCitationDocumentName(detail) || `引用 ${data.label ?? ''}`,
    snippet: extractRagParagraphContent(item?.content || item?.snippet || payload.snippet),
    sourceName: payload.knowledgeName || payload.fileType || '政策文件',
    sourceMeta: payload.page ? `第 ${payload.page} 页` : item?.page ? `第 ${item.page} 页` : '',
    link: payload.previewUrl || payload.downloadUrl,
    type,
  };
}

export function buildCitationDocumentPreview(detail: ChatCitation | null, data: Partial<CitationDisplayData>): CitationPreview | null {
  if (!detail?.sourcePayload) {
    return null;
  }

  const payload = detail.sourcePayload;
  const type = normalizeCitationType(detail.type || data.type);

  if (type === 'web') {
    return {
      title: payload.title || payload.url || `引用 ${data.label ?? ''}`,
      snippet: '',
      sourceName: payload.source || payload.url || '网页',
      sourceMeta: formatCitationWebDate(payload.datePublished || ''),
      link: payload.url || payload.sourceUrl,
      type,
    };
  }

  return {
    title: getCitationDocumentName(detail) || `引用 ${data.label ?? ''}`,
    snippet: '',
    sourceName: payload.knowledgeName || payload.fileType || '政策文件',
    sourceMeta: payload.fileType || '',
    link: payload.previewUrl || payload.downloadUrl,
    type,
  };
}

export function createCitationDetailMap(citations?: ChatCitation[] | null) {
  return (citations ?? []).reduce<Record<string, ChatCitation>>((acc, item) => {
    if (item?.citationId) {
      acc[item.citationId] = item;
    }
    return acc;
  }, {});
}

function buildFallbackCitationData(citation: ChatCitation, label: number): CitationDisplayData | null {
  if (!citation?.citationId) {
    return null;
  }

  const item = citation.sourcePayload?.items?.[0];
  const itemId = String(citation.itemId || item?.itemId || item?.chunkId || item?.chunkIndex || '1');
  const parsed = buildCitationDisplayData(`${citation.citationId}:${itemId}`);

  return {
    label,
    ref: parsed?.ref || `${citation.citationId}:${itemId}`,
    type: parsed?.type || citation.type || 'knowledgeSearch',
    groupKey: parsed?.groupKey || citation.citationId,
    chunkId: parsed?.chunkId || itemId,
    citationId: citation.citationId,
    itemId,
  };
}

export function buildCitationReferenceItems({
  content,
  webContent,
  citations,
}: {
  content: string;
  webContent?: any;
  citations?: ChatCitation[] | null;
}): CitationReferenceItem[] {
  const detailMap = createCitationDetailMap(citations);
  const { transformedContent, citationMap } = transformPrivateCitations(content || '');
  const items: CitationReferenceItem[] = [];
  const seen = new Set<string>();

  Object.values(citationMap).forEach((data) => {
    const key = `private:${data.citationId}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    items.push({
      key,
      data,
      detail: detailMap[data.citationId] ?? null,
    });
  });

  for (const match of transformedContent.matchAll(/\[citation:(\d+)\]/g)) {
    const label = Number(match[1]);
    const preview = getLegacyCitationPreview(webContent, label);
    if (!preview) {
      continue;
    }

    const key = `legacy:${label}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    items.push({
      key,
      data: {
        label,
        ref: `citation:${label}`,
        type: 'web',
        groupKey: String(label),
        chunkId: String(label),
        citationId: `citation:${label}`,
        itemId: String(label),
      },
      legacyPreview: preview,
    });
  }

  if (!items.length && citations?.length) {
    citations.forEach((citation, index) => {
      const data = buildFallbackCitationData(citation, index + 1);
      if (!data) {
        return;
      }

      const key = `detail:${data.citationId}`;
      if (seen.has(key)) {
        return;
      }
      seen.add(key);
      items.push({
        key,
        data,
        detail: citation,
      });
    });
  }

  return items;
}
