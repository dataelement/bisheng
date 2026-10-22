import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useCitationUtilities, useMarkdownServices } from './MarkdownServices';
import type { ChatCitation, CitationDisplayData } from './types';
/** Per-message cache, with the client's distinct forbidden/expired resolution. */
export function useCitationDetails(citations: ChatCitation[] | null | undefined, citationMap: Record<string, CitationDisplayData>) {
  const { createCitationDetailMap, isRagCitation, isTempCitation, getCitationDocumentUrl } = useCitationUtilities();
  const { getCitationDetail, resolveCitationDetails, getCitationUnresolvedReason } = useMarkdownServices();
  const initialMap = useMemo(() => createCitationDetailMap(citations), [citations, createCitationDetailMap]);
  const [details, setDetails] = useState<Record<string, ChatCitation>>(initialMap);
  const [forbidden, setForbidden] = useState<Set<string>>(new Set());
  const [expired, setExpired] = useState<Set<string>>(new Set());
  const cache = useRef<Record<string, ChatCitation | null>>({});
  const requests = useRef<Partial<Record<string, Promise<ChatCitation | null>>>>({});
  const shouldResolve = useCallback((id: string, detail?: ChatCitation | null) => !id.startsWith('citation:')
    && (!detail || ((isRagCitation(detail) || isTempCitation(detail)) && !getCitationDocumentUrl(detail))), [getCitationDocumentUrl, isRagCitation, isTempCitation]);
  useEffect(() => {
    Object.assign(cache.current, initialMap);
    setDetails(current => ({ ...current, ...initialMap }));
  }, [initialMap]);
  useEffect(() => {
    let active = true;
    const ids = [...new Set([...Object.values(citationMap).map(item => item.citationId), ...(citations ?? []).map(item => item.citationId)])]
      .filter(id => !!id && shouldResolve(id, cache.current[id]));
    if (!ids.length) return;
    void resolveCitationDetails(ids).then(items => {
      if (!active) return;
      const nextMap: Record<string, ChatCitation> = {};
      items.forEach(item => { if (item.citationId) { nextMap[item.citationId] = item; cache.current[item.citationId] = item; } });
      if (Object.keys(nextMap).length) setDetails(current => ({ ...current, ...nextMap }));
      const unresolved = ids.filter(id => !cache.current[id]);
      const nextExpired = unresolved.filter(id => getCitationUnresolvedReason(id) === 'expired');
      const nextForbidden = unresolved.filter(id => getCitationUnresolvedReason(id) !== 'expired');
      if (nextExpired.length) setExpired(current => new Set([...current, ...nextExpired]));
      if (nextForbidden.length) setForbidden(current => new Set([...current, ...nextForbidden]));
    }).catch(error => { if (active) console.error('Failed to resolve citation details:', error); });
    return () => { active = false; };
  }, [citationMap, citations, getCitationUnresolvedReason, resolveCitationDetails, shouldResolve]);
  const load = useCallback(async (id: string): Promise<ChatCitation | null> => {
    const cached = cache.current[id];
    if (cached && !shouldResolve(id, cached)) return cached;
    if (requests.current[id]) return requests.current[id];
    const request = getCitationDetail(id).then(detail => { cache.current[id] = detail; return detail; }).finally(() => { delete requests.current[id]; });
    requests.current[id] = request;
    return request;
  }, [getCitationDetail, shouldResolve]);
  return { details, forbidden, expired, load };
}
