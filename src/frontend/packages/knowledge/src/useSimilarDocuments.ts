import { useCallback, useEffect, useRef, useState } from 'react';
import type { SearchableDocument, SimilarDocumentCandidate, SimilarDocumentEvents, SimilarDocumentsServices } from './types';

interface UseSimilarDocumentsProps extends SimilarDocumentEvents {
  spaceId: number;
  fileId: number;
  services: SimilarDocumentsServices;
  linkSuccess: string;
  dismissSuccess: string;
}

export function useSimilarDocuments({ spaceId, fileId, services, linkSuccess, dismissSuccess, ...events }: UseSimilarDocumentsProps) {
  const eventsRef = useRef(events);
  eventsRef.current = events;
  const lifetime = useRef<AbortController | null>(null);
  const writing = useRef(false);
  const writeBlocked = useRef(false);
  const [busy, setBusy] = useState(false);
  const [writeFailed, setWriteFailed] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [search, setSearch] = useState('');
  const [candidateAttempt, setCandidateAttempt] = useState(0);
  const [searchAttempt, setSearchAttempt] = useState(0);
  const [candidates, setCandidates] = useState<SimilarDocumentCandidate[]>([]);
  const [candidatesLoading, setCandidatesLoading] = useState(true);
  const [candidatesError, setCandidatesError] = useState<unknown>(null);
  const [searchResults, setSearchResults] = useState<SearchableDocument[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<unknown>(null);
  const [target, setTarget] = useState<{ document_id: number; title: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    writing.current = false;
    writeBlocked.current = false;
    setBusy(false);
    setWriteFailed(false);
    setKeyword('');
    setSearch('');
    setTarget(null);
    return () => {
      controller.abort();
      eventsRef.current.onBusyChange?.(false);
    };
  }, [spaceId, fileId, services]);

  useEffect(() => {
    const controller = new AbortController();
    setCandidates([]);
    setCandidatesError(null);
    setCandidatesLoading(true);
    void services.getRecommendations(fileId, controller.signal).then((result) => {
      if (!controller.signal.aborted) setCandidates(result);
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        setCandidatesError(error);
        eventsRef.current.onError(error);
      }
    }).finally(() => {
      if (!controller.signal.aborted) setCandidatesLoading(false);
    });
    return () => controller.abort();
  }, [services, fileId, candidateAttempt]);

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(keyword.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [keyword]);

  useEffect(() => {
    const controller = new AbortController();
    setSearchResults([]);
    setSearchError(null);
    if (!search) {
      setSearchLoading(false);
      return () => controller.abort();
    }
    setSearchLoading(true);
    void services.searchDocuments(spaceId, search, fileId, controller.signal).then((result) => {
      if (!controller.signal.aborted) setSearchResults(result);
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        setSearchError(error);
        eventsRef.current.onError(error);
      }
    }).finally(() => {
      if (!controller.signal.aborted) setSearchLoading(false);
    });
    return () => controller.abort();
  }, [services, spaceId, fileId, search, searchAttempt]);

  const submitSearch = () => {
    const next = keyword.trim();
    setSearch(next);
    if (next === search) setSearchAttempt((attempt) => attempt + 1);
  };

  const handleWrite = async (action: 'relate' | 'dismiss') => {
    const controller = lifetime.current;
    if (!controller || controller.signal.aborted || writing.current || writeBlocked.current || (action === 'relate' && !target)) return;
    writing.current = true;
    setBusy(true);
    eventsRef.current.onBusyChange?.(true);
    try {
      if (action === 'relate' && target) {
        const response = await services.relate(fileId, target.document_id, controller.signal);
        if (controller.signal.aborted) return;
        setTarget(null);
        eventsRef.current.onSuccess(linkSuccess);
        eventsRef.current.onLinked?.(response);
      } else {
        await services.dismiss(fileId, controller.signal);
        if (controller.signal.aborted) return;
        eventsRef.current.onSuccess(dismissSuccess);
        eventsRef.current.onDismissed?.();
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        // A rejected response does not prove that the server did not commit.
        writeBlocked.current = true;
        setWriteFailed(true);
        setTarget(null);
        eventsRef.current.onUncertain?.();
        eventsRef.current.onError(error);
      }
    } finally {
      if (!controller.signal.aborted) {
        writing.current = false;
        setBusy(false);
        eventsRef.current.onBusyChange?.(false);
      }
    }
  };

  const selectTarget = (next: { document_id: number; title: string }) => {
    if (!writing.current && !writeBlocked.current && !lifetime.current?.signal.aborted) setTarget(next);
  };
  const cancelTarget = () => { if (!writing.current) setTarget(null); };
  const retryCandidates = useCallback(() => setCandidateAttempt((attempt) => attempt + 1), []);
  const retrySearch = useCallback(() => setSearchAttempt((attempt) => attempt + 1), []);

  return { busy, writeFailed, keyword, setKeyword, search, submitSearch, candidates, candidatesLoading, candidatesError, searchResults, searchLoading, searchError, retryCandidates, retrySearch, target, selectTarget, cancelTarget, confirmTarget: () => handleWrite('relate'), dismiss: () => handleWrite('dismiss') };
}
