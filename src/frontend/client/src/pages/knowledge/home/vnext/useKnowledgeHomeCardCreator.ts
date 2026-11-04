import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSpaceInfoApi, type KnowledgeSpace } from '~/api/knowledge';
import { isDemoId } from '~/mock/demo/ids';

/** Resolve omitted creator names only after their card enters the viewport. */
export function useKnowledgeHomeCardCreator(space: KnowledgeSpace) {
  const cardRef = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);
  const creator = space.creator?.trim();
  const needsCreator = !creator && !!space.creatorId && !isDemoId(space.id);

  useEffect(() => {
    const card = cardRef.current;
    if (!card || !needsCreator) return;
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setVisible(true);
        observer.disconnect();
      }
    });
    observer.observe(card);
    return () => observer.disconnect();
  }, [needsCreator]);

  const creatorInfo = useQuery({
    queryKey: ['knowledgeHomeCreator', space.id, space.creatorId],
    queryFn: () => getSpaceInfoApi(space.id),
    enabled: visible && needsCreator,
    staleTime: 5 * 60 * 1000,
    retry: false,
    refetchOnWindowFocus: false,
  });

  return { cardRef, creator: creator || creatorInfo.data?.creator?.trim() };
}
