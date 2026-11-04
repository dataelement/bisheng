import type { MutableRefObject, ReactNode } from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import Convo from '~/components/Conversations/Convo';
import { ApiRequestFailure } from '~/components/ApiRequestFailure';
import { Spinner } from '~/components/svg';
import { useLocalize, useNavScrolling, useScrollRevealRef } from '~/hooks';
import type { useConversationsInfiniteQuery } from '~/hooks/queries/data-provider';
import type { ConversationListResponse } from '~/types/chat';
import { cn } from '~/utils';
import { useMockProjectChats } from './projectsStore';
import { SidebarSectionLabel } from './SidebarSectionLabel';

interface SidebarConversationListProps {
  /** Rendered inside the scroll area above the 对话 label (the 项目 section), so the
   *  sidebar's middle scrolls as one column instead of squeezing the list under it. */
  leading?: ReactNode;
  query: ReturnType<typeof useConversationsInfiniteQuery>;
  scrollPosition: MutableRefObject<number>;
  onNavigate: () => void;
}

/**
 * 对话 section of the workbench sidebar (Figma 13139:111611): one flat, infinitely
 * scrolling list — no date groups — that owns the sidebar's remaining height. It is
 * also the sidebar's only scroll container: whatever comes in `leading` scrolls with it.
 */
export function SidebarConversationList({ leading, query, scrollPosition, onNavigate }: SidebarConversationListProps) {
  const localize = useLocalize();
  const [showLoading, setShowLoading] = useState(false);
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage } = query;

  const { containerRef, moveToTop } = useNavScrolling<ConversationListResponse>({
    setShowLoading,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  });

  const scrollRevealRef = useScrollRevealRef<HTMLDivElement>();
  const setHistoryScrollRef = useCallback((node: HTMLDivElement | null) => {
    if (!node && containerRef.current) scrollPosition.current = containerRef.current.scrollTop;
    containerRef.current = node;
    scrollRevealRef(node);
    if (node) node.scrollTop = scrollPosition.current;
  }, [containerRef, scrollRevealRef, scrollPosition]);

  // MOCK: a conversation moved into a project leaves the flat list and shows up
  // under its folder above (see projectsStore).
  const projectChats = useMockProjectChats();
  const conversations = useMemo(
    () =>
      (data?.pages.flatMap((page) => page.conversations).filter((convo) => convo != null) ?? []).filter(
        (convo) => projectChats[convo.conversationId ?? ''] == null,
      ),
    [data, projectChats],
  );

  // Edge fades, same idea as the knowledge-space menu: shown only while there is
  // content beyond that edge, so a list that fits shows no mask at all.
  const [canScrollUp, setCanScrollUp] = useState(false);
  const [canScrollDown, setCanScrollDown] = useState(false);
  const updateScrollShadows = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const { scrollTop, scrollHeight, clientHeight } = el;
    setCanScrollUp(scrollTop > 0);
    setCanScrollDown(scrollTop + clientHeight < scrollHeight - 1);
  }, [containerRef]);
  useEffect(() => {
    updateScrollShadows();
  }, [conversations, updateScrollShadows]);

  return (
    <section className="flex min-h-0 w-full flex-1 flex-col">
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div
          aria-hidden
          className={cn(
            'pointer-events-none absolute left-0 right-0 top-0 z-10 h-8 bg-gradient-to-b from-white to-transparent transition-opacity duration-150',
            canScrollUp ? 'opacity-100' : 'opacity-0',
          )}
        />
        <div
          aria-hidden
          className={cn(
            'pointer-events-none absolute bottom-0 left-0 right-0 z-10 h-8 bg-gradient-to-t from-white to-transparent transition-opacity duration-150',
            canScrollDown ? 'opacity-100' : 'opacity-0',
          )}
        />
        <div
          ref={setHistoryScrollRef}
          onScroll={(event) => {
            scrollPosition.current = event.currentTarget.scrollTop;
            updateScrollShadows();
          }}
          // -mx-1/px-1 widens the scrollport past the rows' edges so the rename
          // ring (a 1px shadow) isn't clipped.
          className="scrollbar-on-scroll -mx-1 min-h-0 flex-1 overflow-y-auto px-1"
        >
          {leading}
          <SidebarSectionLabel>{localize('com_workbench_sidebar.conversations')}</SidebarSectionLabel>
          {query.isError && <ApiRequestFailure error={query.error} onRetry={query.refetch} />}
          {query.isSuccess && !conversations.length && (
            <p className="px-2 py-3 text-caption text-text-3">{localize('com_app_chat_sidebar_empty')}</p>
          )}
          {conversations.map((convo) => (
            <Convo
              key={convo.conversationId}
              compact
              // The flat list has no "today" group, so no row stands in for /c/new.
              isLatestConvo={false}
              conversation={convo}
              retainView={moveToTop}
              toggleNav={onNavigate}
            />
          ))}
          {(isFetchingNextPage || showLoading) && (
            <Spinner className="m-1 mx-auto mb-4 h-4 w-4 text-text-1" />
          )}
        </div>
      </div>
    </section>
  );
}
