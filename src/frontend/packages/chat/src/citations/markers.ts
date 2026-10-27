import type { CitationDisplayData } from './types';
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
export function normalizeCitationMarkers(content: string) {
    return content.replace(/(\\+)u([eE]20[012])/g, (match, slashes, code) => {
        if (slashes.length % 2 !== 0) {
            const prefix = slashes.slice(1);
            const marker = code.toLowerCase();
            if (marker === 'e200')
                return prefix + CITATION_START;
            if (marker === 'e201')
                return prefix + CITATION_SEPARATOR;
            if (marker === 'e202')
                return prefix + CITATION_END;
        }
        return match;
    });
}
export const CITATION_START = '\ue200';
export const CITATION_SEPARATOR = '\ue201';
export const CITATION_END = '\ue202';
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
export function parseCitationRef(ref: string) {
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
