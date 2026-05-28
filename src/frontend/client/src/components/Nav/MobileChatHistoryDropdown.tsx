import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useSearchContext } from '~/Providers';
import { Conversations } from '~/components/Conversations';
import { Spinner } from '~/components/svg';
import { useConversationsInfiniteQuery } from '~/hooks/queries/data-provider';
import { useAuthContext, useLocalize, useNavScrolling } from '~/hooks';
import { Plus } from 'lucide-react';
import type { ConversationListResponse } from '~/types/chat';
import { cn } from '~/utils';

interface MobileChatHistoryDropdownProps {
    open: boolean;
    onClose: () => void;
    onNewChat: () => void;
    /** Top offset (CSS) so the panel anchors right under the H5 title bar. */
    topOffset?: string;
}

/**
 * H5 chat history dropdown — anchored under MobileNav's title row.
 *
 * Replaces the original left-edge `<Nav>` drawer on mobile while keeping every existing
 * data flow intact: same `useConversationsInfiniteQuery` hook, same `<Conversations>`
 * renderer, same search-context integration, same infinite-scroll behaviour. Only the
 * outer chrome (positioning, "+开启新对话" footer button) is new.
 */
export function MobileChatHistoryDropdown({
    open,
    onClose,
    onNewChat,
    topOffset = 'calc(env(safe-area-inset-top, 0px) + 52px)',
}: MobileChatHistoryDropdownProps) {
    const localize = useLocalize();
    const { isAuthenticated } = useAuthContext();
    const [showLoading, setShowLoading] = useState(false);
    const { pageNumber, searchQuery, searchQueryRes } = useSearchContext();
    const tags: string[] = [];

    const { data, fetchNextPage, hasNextPage, isFetchingNextPage, refetch } =
        useConversationsInfiniteQuery(
            {
                pageNumber: pageNumber.toString(),
                isArchived: false,
                tags: tags.length === 0 ? undefined : tags,
            },
            { enabled: isAuthenticated && open },
        );

    useEffect(() => {
        refetch();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [tags]);

    const { containerRef, moveToTop } = useNavScrolling<ConversationListResponse>({
        setShowLoading,
        hasNextPage: searchQuery ? searchQueryRes?.hasNextPage : hasNextPage,
        fetchNextPage: searchQuery ? searchQueryRes?.fetchNextPage : fetchNextPage,
        isFetchingNextPage: searchQuery
            ? searchQueryRes?.isFetchingNextPage ?? false
            : isFetchingNextPage,
    });

    const conversations = useMemo(
        () =>
            (searchQuery ? searchQueryRes?.data : data)?.pages.flatMap((page) => page.conversations) ||
            [],
        [data, searchQuery, searchQueryRes?.data],
    );

    if (!open || typeof document === 'undefined') return null;

    // Render through a portal so the dropdown escapes MobileNav's stacking context (its
    // sibling in DOM holds the chat content + input form which would otherwise paint on top).
    return createPortal(
        <div
            className="fixed inset-x-0 bottom-0 z-[80] flex flex-col bg-white"
            style={{ top: topOffset }}
            role="dialog"
            aria-modal="true"
            aria-label={localize('com_ui_chat_list')}
        >
            {/* Conversation list — same renderer as the desktop Nav drawer. */}
            <div
                ref={containerRef}
                className={cn(
                    'scrollbar-trigger min-h-0 flex-1 overflow-y-auto px-2 py-2',
                )}
            >
                <Conversations
                    conversations={conversations}
                    moveToTop={moveToTop}
                    toggleNav={onClose}
                />
                {(isFetchingNextPage || showLoading) && (
                    <Spinner className="m-1 mx-auto mb-4 h-4 w-4 text-text-primary" />
                )}
            </div>

            {/* Bottom action: 开启新对话 — same style as channel/knowledge dropdown bottom button */}
            <div className="shrink-0 px-3 pt-2 pb-[max(12px,env(safe-area-inset-bottom))]">
                <button
                    type="button"
                    onClick={() => {
                        onClose();
                        onNewChat();
                    }}
                    className="flex w-full shrink-0 items-center justify-center gap-1 rounded-[6px] border border-[#E3E3E3] bg-white px-3 py-[5px] text-[14px] leading-[22px] text-[#212121] transition-colors fine-pointer:hover:bg-[#F7F8FA]"
                >
                    <Plus className="size-4 text-[#86909C]" strokeWidth={2} />
                    {localize('com_ui_new_chat')}
                </button>
            </div>
        </div>,
        document.body,
    );
}
