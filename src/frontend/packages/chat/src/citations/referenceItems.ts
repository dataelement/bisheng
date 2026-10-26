import type { ChatCitation, CitationDisplayData, CitationPreview, CitationReferenceItem } from './types';
import { buildCitationDisplayData, transformPrivateCitations } from './markers';
interface ReferenceUtilities {
  createCitationDetailMap: (citations?: ChatCitation[] | null) => Record<string, ChatCitation>;
  getLegacyCitationPreview: (webContent: unknown, label?: number) => CitationPreview | null;
}
export function createReferenceUtilities({createCitationDetailMap,getLegacyCitationPreview}: ReferenceUtilities) {
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

function buildCitationReferenceItems({
  content,
  webContent,
  citations,
}: {
  content: string;
  webContent?: unknown;
  citations?: ChatCitation[] | null;
}): CitationReferenceItem[] {
  const detailMap = createCitationDetailMap(citations);
  const { transformedContent, citationMap } = transformPrivateCitations(content || '');
  const items: CitationReferenceItem[] = [];
  const seen = new Set<string>();
  const grouped = new Map<string, CitationReferenceItem>();

  Object.values(citationMap).forEach((data) => {
    const key = `private:${data.citationId}`;
    const existing = grouped.get(key);
    if (existing) {
      if (data.itemId && !existing.itemIds?.includes(data.itemId)) {
        existing.itemIds = [...(existing.itemIds || []), data.itemId];
      }
      return;
    }
    grouped.set(key, {
      key,
      data,
      itemIds: data.itemId ? [data.itemId] : [],
      detail: detailMap[data.citationId] ?? null,
    });
  });
  items.push(...grouped.values());
  grouped.forEach((item) => seen.add(item.key));

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

return {buildCitationReferenceItems};
}
