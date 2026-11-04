import type { ChatCitation, CitationDisplayData } from './types';
function mapBareCitationRefs(content: string, replace: (ref: string, token: string) => string) {
    // Leave code, links, existing protocol spans and generated placeholders literal.
    const tokens = /(`+)[\s\S]*?\1|~~~[\s\S]*?~~~|\[[^\]\n]*\]\([^\n)]*\)|\[citationref:[^\]]*\]|\ue200[^\ue202]*\ue202|https?:\/\/[^\s<>]+|((?<![\w/:])(?:knowledgesearch|websearch|tempsearch|articlesearch)_[a-fA-F0-9]+:\d+(?![\w:.-]))[\ue201\ue202]*/g;
    return content.replace(tokens, (token: string, _ticks: string | undefined, ref: string | undefined) => ref ? replace(ref, token) : token);
}
/** Candidates are untrusted; callers must resolve them before restoring badges. */
export function getBareCitationRefs(content: string): string[] {
    const refs = new Set<string>();
    mapBareCitationRefs(normalizeCitationMarkers(content), (ref, token) => { refs.add(ref); return token; });
    return [...refs];
}
/** Recover missing wrappers only when the exact source and chunk were supplied. */
function restoreRegisteredBareCitations(content: string, citations?: ChatCitation[] | null) {
    const registeredRefs = new Set<string>();
    for (const citation of citations || []) {
        if (citation.itemId != null) registeredRefs.add(`${citation.citationId}:${citation.itemId}`);
        for (const item of citation.sourcePayload?.items || []) {
            if (item.itemId != null) registeredRefs.add(`${citation.citationId}:${item.itemId}`);
        }
    }
    if (!registeredRefs.size) return content;
    // Consume leftover protocol characters only for an exact registered reference.
    return mapBareCitationRefs(content, (ref, token) => registeredRefs.has(ref)
        ? `${CITATION_START}${ref}${CITATION_END}` : token);
}

export function transformPrivateCitations(content: string, citations?: ChatCitation[] | null) {
    const normalizedCitationContent = restoreRegisteredBareCitations(normalizeCitationMarkers(content), citations);
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
