/**
 * Message list for the AI assistant panel.
 * Renders messages as a tree structure with sibling paging.
 * Each node with multiple children shows SiblingSwitch for navigation.
 */
import { ArrowDownIcon, CornerDownRightIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSetRecoilState } from "recoil";
import { Button } from "~/components";
import type { CitationReferencesDesktopPayload } from "./Messages/Content/CitationReferencesDrawer";
import { cn } from "~/utils";
import AiMessageBubble from "./AiMessageBubble";
import type { ChatMessage } from "~/api/chatApi";
import { buildMessageTree } from "~/api/chatApi";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import store from "~/store";
import HeaderTitle from "./HeaderTitle";

interface AiChatMessagesProps {
    messages: ChatMessage[];
    conversationId?: string;
    title?: string;
    isLoading?: boolean;
    isStreaming?: boolean;
    presetQuestions?: string[];
    shareToken?: string;
    /** When true, hides the share button in the header */
    hideShare?: boolean;
    /** When true, hides the sticky header title bar */
    hideHeaderTitle?: boolean;
    /** When true, renders messages as a flat list without tree/sibling navigation */
    flatMode?: boolean;
    /** Knowledge space AI panel: full-width column, 14px body, gray user / borderless assistant */
    knowledgeChatLayout?: boolean;
    /** Overrides empty-state line under the illustration (e.g. knowledge folder QA hint from parent) */
    emptyStateHint?: string;
    /** Optional width utility classes for the inner message column */
    contentWidthClassName?: string;
    onPresetClick?: (question: string) => void;
    onRegenerate?: (parentMessageId: string) => void;
    onOpenCitationPanel?: (payload: CitationReferencesDesktopPayload) => void;
    activeCitationMessageId?: string | null;
}

/**
 * Recursively render a message tree node.
 * Each level picks one sibling (via siblingIdx state) and renders its children below.
 */
function MessageTreeNode({
    siblings,
    isStreaming,
    totalMessages,
    currentIndex,
    onRegenerate,
    knowledgeChatLayout,
    onOpenCitationPanel,
    activeCitationMessageId,
}: {
    siblings: ChatMessage[];
    isStreaming?: boolean;
    totalMessages: number;
    currentIndex: number;
    onRegenerate?: (parentMessageId: string) => void;
    knowledgeChatLayout?: boolean;
    onOpenCitationPanel?: (payload: CitationReferencesDesktopPayload) => void;
    activeCitationMessageId?: string | null;
}) {
    // Local sibling index for this group of siblings
    const [siblingIdx, setSiblingIdx] = useState(0);

    // Reset siblingIdx when siblings change (new message added)
    useEffect(() => {
        if (siblings.length > 0 && siblingIdx >= siblings.length) {
            setSiblingIdx(siblings.length - 1);
        }
    }, [siblings.length, siblingIdx]);

    // When a new sibling is added (regenerate), show the latest one
    useEffect(() => {
        if (siblings.length > 1) {
            setSiblingIdx(siblings.length - 1);
        }
    }, [siblings.length]);

    if (!siblings || siblings.length === 0) return null;

    const message = siblings[siblingIdx] ?? siblings[siblings.length - 1];
    if (!message) return null;

    const children = message.children ?? [];
    const isLastInChain = children.length === 0;
    const isLastMessage = isLastInChain && !message.isCreatedByUser;

    return (
        <>
            <AiMessageBubble
                message={message}
                isLatest={isLastMessage}
                isStreaming={isStreaming && isLastMessage}
                onRegenerate={
                    !message.isCreatedByUser && !isStreaming
                        ? () => onRegenerate?.(message.parentMessageId)
                        : undefined
                }
                siblingIdx={siblingIdx}
                siblingCount={siblings.length}
                setSiblingIdx={setSiblingIdx}
                knowledgeChatLayout={knowledgeChatLayout}
                onOpenCitationPanel={onOpenCitationPanel}
                activeCitationMessageId={activeCitationMessageId}
            />
            {/* Recursively render children */}
            {children.length > 0 && (
                <MessageTreeNode
                    siblings={children}
                    isStreaming={isStreaming}
                    totalMessages={totalMessages}
                    currentIndex={currentIndex + 1}
                    onRegenerate={onRegenerate}
                    knowledgeChatLayout={knowledgeChatLayout}
                    onOpenCitationPanel={onOpenCitationPanel}
                    activeCitationMessageId={activeCitationMessageId}
                />
            )}
        </>
    );
}

export default function AiChatMessages({
    messages,
    conversationId = "",
    title = "",
    isLoading,
    isStreaming,
    presetQuestions = [],
    shareToken = '',
    hideShare = false,
    hideHeaderTitle = false,
    flatMode = false,
    knowledgeChatLayout = false,
    emptyStateHint,
    contentWidthClassName,
    onPresetClick,
    onRegenerate,
    onOpenCitationPanel,
    activeCitationMessageId,
}: AiChatMessagesProps) {
    const localize = useLocalize();
    const isNarrowViewport = usePrefersMobileLayout();
    const setChatMobileHeader = useSetRecoilState(store.chatMobileHeaderState);
    const scrollRef = useRef<HTMLDivElement>(null);
    const endRef = useRef<HTMLDivElement>(null);
    const [showScrollBtn, setShowScrollBtn] = useState(false);
    // Track whether user has manually scrolled up
    const isUserScrolledUp = useRef(false);

    // Build message tree from flat array (skipped in flat mode)
    const tree = useMemo(() => (flatMode ? [] : buildMessageTree(messages)), [messages, flatMode]);

    const headerTitleText = useMemo(() => {
        const raw = tree[0]?.flow_name || title;
        if (raw != null && String(raw).trim() !== "") return String(raw).trim();
        return localize("com_ui_new_chat");
    }, [tree, title, localize]);

    useEffect(() => {
        if (hideHeaderTitle) {
            setChatMobileHeader(null);
            return;
        }
        setChatMobileHeader({
            title: headerTitleText,
            conversationId,
            flowId: "",
            flowType: 15,
            readOnly: !!shareToken,
            hideShare,
        });
        return () => setChatMobileHeader(null);
    }, [
        hideHeaderTitle,
        headerTitleText,
        conversationId,
        shareToken,
        hideShare,
        setChatMobileHeader,
    ]);

    // Check if user is near bottom
    const checkNearBottom = () => {
        if (!scrollRef.current) return;
        const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
        const distFromBottom = scrollHeight - scrollTop - clientHeight;
        const nearBottom = distFromBottom < 100;
        isUserScrolledUp.current = !nearBottom;
        setShowScrollBtn(!nearBottom);
    };

    // Auto-scroll to bottom on new messages — only if user hasn't scrolled up
    useEffect(() => {
        if (!isUserScrolledUp.current && endRef.current) {
            endRef.current.scrollIntoView({ behavior: "smooth" });
        }
    }, [messages]);

    // ResizeObserver to detect content height changes (e.g. thinking block collapse/expand)
    useEffect(() => {
        const container = scrollRef.current;
        if (!container) return;
        const observer = new ResizeObserver(() => {
            checkNearBottom();
        });
        // Observe the inner content div for size changes
        const inner = container.firstElementChild;
        if (inner) observer.observe(inner);
        return () => observer.disconnect();
    }, []);

    // Show/hide scroll-to-bottom button and track user scroll position
    const handleScroll = () => {
        checkNearBottom();
    };

    const scrollToBottom = () => {
        isUserScrolledUp.current = false;
        endRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    const hasMessages = messages.length > 0;

    // --- Empty state ---
    if (!hasMessages && !isLoading) {
        return (
            <div
                className="flex-1 overflow-y-auto scrollbar-on-hover px-5 py-4 flex flex-col items-center justify-center"
                style={{
                    transitionProperty: 'background-color',
                    transitionDuration: '350ms',
                    transitionTimingFunction: 'ease-in-out'
                }}
            >
                <div className="mb-6">
                    <img
                        className="size-[80px] object-contain mx-auto block"
                        src={`${__APP_ENV__.BASE_URL}/assets/channel/ai-home.png`}
                        alt="AI Assistant"
                    />
                    <p className="mt-[22px] text-center text-sm text-[#86909c]">
                        {emptyStateHint ?? localize("com_knowledge.qa_current_article")}
                    </p>
                    {presetQuestions.length > 0 && (
                        <div className="w-full flex flex-col gap-3 pt-[22px]">
                            {presetQuestions.map((q, i) => (
                                <Button
                                    key={i}
                                    variant="ghost"
                                    className="bg-gray-50 px-3 py-1 text-left text-sm font-normal text-[#86909c] transition-colors hover:bg-[#E6EDFC] hover:text-[#165DFF] active:bg-[#E6EDFC] rounded-lg flex items-center gap-1 group w-fit"
                                    onClick={() => onPresetClick?.(q)}
                                >
                                    <div className="size-4 flex items-center justify-center">
                                        <span className="w-1.5 h-1.5 rounded-full bg-primary group-hover:hidden group-active:hidden" />
                                        <CornerDownRightIcon className="size-4 text-primary hidden group-hover:block group-active:block" />
                                    </div>
                                    {q}
                                </Button>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        );
    }

    // --- Loading state ---
    if (isLoading) {
        return (
            <div className="flex-1 flex items-center justify-center">
                <div className="animate-spin rounded-full h-6 w-6 border-2 border-primary border-t-transparent" />
            </div>
        );
    }

    // --- Messages (tree rendering) ---
    return (
        <div className="relative flex h-full min-h-0 flex-1 flex-col overflow-hidden">
            {!hideHeaderTitle && (
                <HeaderTitle
                    readOnly={!!shareToken}
                    hideShare={hideShare}
                    conversation={{ title: tree[0]?.flow_name || title, flowId: "", conversationId, flowType: 15 }}
                />
            )}
            <div
                ref={scrollRef}
                className={cn(
                    "min-h-0 flex-1 overflow-y-auto scrollbar-on-hover",
                    hideHeaderTitle
                        ? "pt-2"
                        : isNarrowViewport
                          ? "pt-11"
                          : "pt-14",
                )}
                onScroll={handleScroll}
            >
                <div
                    className={cn(
                        "flex min-h-full w-full flex-col py-2",
                        contentWidthClassName ?? (knowledgeChatLayout ? "max-w-none" : "max-w-[768px] mx-auto")
                    )}
                >
                    {flatMode ? (
                        /* Flat mode: render messages as a simple list */
                        messages.map((message, idx) => {
                            const isLast = idx === messages.length - 1;
                            const isLastBot = isLast && !message.isCreatedByUser;
                            return (
                                <AiMessageBubble
                                    key={message.messageId}
                                    message={message}
                                    isLatest={isLastBot}
                                    isStreaming={isStreaming && isLastBot}
                                    onRegenerate={
                                        !message.isCreatedByUser && isLastBot && !isStreaming
                                            ? () => onRegenerate?.(message.parentMessageId)
                                            : undefined
                                    }
                                    knowledgeChatLayout={knowledgeChatLayout}
                                    onOpenCitationPanel={onOpenCitationPanel}
                                    activeCitationMessageId={activeCitationMessageId}
                                />
                            );
                        })
                    ) : (
                        /* Tree mode: render messages as tree with sibling navigation */
                        tree.length > 0 && (
                            <MessageTreeNode
                                siblings={tree}
                                isStreaming={isStreaming}
                                totalMessages={messages.length}
                                currentIndex={0}
                                onRegenerate={onRegenerate}
                                knowledgeChatLayout={knowledgeChatLayout}
                                onOpenCitationPanel={onOpenCitationPanel}
                                activeCitationMessageId={activeCitationMessageId}
                            />
                        )
                    )}
                    <div ref={endRef} className="h-0 shrink-0" />
                </div>
            </div>
            {/* Scroll to bottom button */}
            {showScrollBtn && (
                <div className="absolute -bottom-4 w-full h-0 flex justify-center z-10">
                    <button
                        type="button"
                        onClick={scrollToBottom}
                        className="flex items-center h-8 justify-center gap-2 rounded-[6px] border border-[#EBECF0] bg-white/80 backdrop-blur-[4px] px-2.5 text-sm leading-5 text-neutral-800 hover:bg-white/90 transition-colors"
                    >
                        <ArrowDownIcon size={16} />
                        <span className="text-sm">回到底部</span>
                    </button>
                </div>
            )}
        </div>
    );
}
