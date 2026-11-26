import { TooltipProvider } from '@bisheng/ui';
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import type { HomeSpace } from './homeSpaces';
import styles from './KnowledgeHomeNext.module.css';

export const KNOWLEDGE_HOME_BATCH_SIZE = 48;

interface KnowledgeHomeGridProps {
  items: HomeSpace[];
  renderCard: (item: HomeSpace, index: number) => ReactNode;
  scrollRef: RefObject<HTMLDivElement>;
}

export function KnowledgeHomeGrid({ items, renderCard, scrollRef }: KnowledgeHomeGridProps) {
  const [limit, setLimit] = useState(KNOWLEDGE_HOME_BATCH_SIZE);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const hasMore = items.length > limit;

  useLayoutEffect(() => {
    const scroller = scrollRef.current;
    if (scroller) scroller.scrollTop = 0;
  }, [scrollRef]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!hasMore || !sentinel) return;

    const scroller = scrollRef.current;
    const loadMore = () => setLimit((current) => Math.max(current, limit + KNOWLEDGE_HOME_BATCH_SIZE));
    if (typeof IntersectionObserver === 'undefined') {
      const checkScroll = () => {
        if (scroller?.clientHeight && scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop <= 320) loadMore();
      };
      checkScroll();
      scroller?.addEventListener('scroll', checkScroll, { passive: true });
      return () => scroller?.removeEventListener('scroll', checkScroll);
    }

    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) loadMore();
    }, { root: scroller, rootMargin: '0px 0px 320px' });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, limit, scrollRef]);

  return (
    <TooltipProvider>
      <div className={styles.grid} onFocusCapture={(event) => {
        // Append before Tab can leave the grid when focus reaches the last card.
        if (hasMore && event.currentTarget.lastElementChild?.contains(event.target)) {
          setLimit((current) => Math.max(current, limit + KNOWLEDGE_HOME_BATCH_SIZE));
        }
      }}>
        {items.slice(0, limit).map(renderCard)}
      </div>
      {hasMore && <div ref={sentinelRef} className="h-px" aria-hidden="true" />}
    </TooltipProvider>
  );
}
