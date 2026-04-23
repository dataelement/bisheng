/**
 * Single message bubble for user / assistant messages.
 */
import {
    BotIcon,
    CheckIcon,
    ChevronLeftIcon,
    ChevronRightIcon,
    CopyIcon,
    Loader2,
    RefreshCwIcon
} from "lucide-react";
import { memo, useCallback, useMemo, useState, useRef } from "react";
import Thinking from "~/components/Artifacts/Thinking";
import AgentThinkingHeader from "~/components/Chat/Messages/AgentThinkingHeader";
import ToolCallDisplay from "~/components/Chat/Messages/ToolCallDisplay";
import Markdown from "~/components/Chat/Messages/Content/Markdown";
import CitationReferencesDrawer, { type CitationReferencesDesktopPayload } from "~/components/Chat/Messages/Content/CitationReferencesDrawer";
import SearchWebUrls from "~/components/Chat/Messages/Content/SearchWebUrls";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
import { TextToSpeechButton } from "~/components/Voice/TextToSpeechButton";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import { useAuthContext } from "~/hooks";
import MessageSource from "~/pages/appChat/components/MessageSource";
import ResouceModal from "~/pages/appChat/components/ResouceModal";
import { copyText, cn } from "~/utils";
import type { AgentEvent, ChatMessage } from "~/api/chatApi";
import Image from "~/components/Chat/Messages/Content/Image";
import { FileIcon, getFileTypebyFileName } from "~/components/ui/icon/File/FileIcon";

interface AiMessageBubbleProps {
    message: ChatMessage;
    isLatest?: boolean;
    isStreaming?: boolean;
    onRegenerate?: () => void;
    // Sibling paging
    siblingIdx?: number;
    siblingCount?: number;
    setSiblingIdx?: (idx: number) => void;
    /** Knowledge space AI: gray user bubble, borderless assistant, 14px body, full width */
    knowledgeChatLayout?: boolean;
    onOpenCitationPanel?: (payload: CitationReferencesDesktopPayload) => void;
    activeCitationMessageId?: string | null;
}

// --- Copy button with feedback ---
function CopyButton({ text }: { text: string }) {
    const [copied, setCopied] = useState(false);
    const handleCopy = useCallback((event: React.MouseEvent<HTMLButtonElement>) => {
        event.preventDefault();
        event.stopPropagation();
        copyText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    }, [text]);

    return (
        <button
            type="button"
            onClick={handleCopy}
            className="flex size-6 items-center justify-center rounded-[6px] backdrop-blur-[4px] transition-colors hover:bg-[#F7F7F7]"
            title="复制"
            aria-label="复制"
        >
            {copied ? <CheckIcon size={14} className="text-[#818181]" /> : <CopyIcon size={14} className="text-[#818181]" />}
        </button>
    );
}

// --- Sibling Switch (prev / next paging) ---
function SiblingSwitch({
    siblingIdx,
    siblingCount,
    setSiblingIdx,
}: {
    siblingIdx: number;
    siblingCount: number;
    setSiblingIdx: (idx: number) => void;
}) {
    if (siblingCount <= 1) return null;
    return (
        <div className="flex items-center gap-1 text-xs text-gray-400">
            <button
                type="button"
                className="p-0.5 rounded hover:bg-gray-100 disabled:opacity-30"
                onClick={() => setSiblingIdx(siblingIdx - 1)}
                disabled={siblingIdx === 0}
            >
                <ChevronLeftIcon size={14} />
            </button>
            <span className="tabular-nums text-[11px]">{siblingIdx + 1} / {siblingCount}</span>
            <button
                type="button"
                className="p-0.5 rounded hover:bg-gray-100 disabled:opacity-30"
                onClick={() => setSiblingIdx(siblingIdx + 1)}
                disabled={siblingIdx === siblingCount - 1}
            >
                <ChevronRightIcon size={14} />
            </button>
        </div>
    );
}

/**
 * Parse a leading `:::tag {"id":..,"name":".."}:::` block out of a user
 * message and return the chip data + remaining text. The same on-the-wire
 * encoding is produced by `useFolderChat.sendMessage` and rebuilt from
 * persisted history in `parseStreamHistoryItem`, so the chip survives reloads.
 */
function parseUserMessageText(text: string): {
    tag: { id: number; name: string } | null;
    bodyText: string;
} {
    if (!text) return { tag: null, bodyText: "" };
    const match = text.match(/^:::tag\s*([\s\S]*?):::\s*\n?/);
    if (!match) return { tag: null, bodyText: text };
    let tag: { id: number; name: string } | null = null;
    try {
        const parsed = JSON.parse(match[1].trim());
        if (parsed && typeof parsed.name === "string") {
            tag = { id: Number(parsed.id) || 0, name: parsed.name };
        }
    } catch {
        // Malformed tag block — fall through and treat the whole thing as text
        return { tag: null, bodyText: text };
    }
    return { tag, bodyText: text.slice(match[0].length) };
}

/**
 * Parse :::thinking xxx::: and :::web xxx::: from message text.
 * Returns { thinkingContent, webContent, regularContent }.
 */
function parseMessageText(text: string) {
    if (!text) return { thinkingContent: "", webContent: [] as any[], regularContent: "" };

    // Extract thinking block
    const thinkingMatch = text.match(/:::thinking([\s\S]*?):::/);
    let regularContent = text;
    if (thinkingMatch) {
        regularContent = text.replace(/:::thinking[\s\S]*?:::/, "").trim();
    }

    // Extract web block
    let webContent: any[] = [];
    const webMatch = regularContent.match(/:::web([\s\S]*?):::/);
    if (webMatch) {
        regularContent = regularContent.replace(/:::web[\s\S]*?:::/, "").trim();
        try {
            const str = webMatch[1].trim();
            webContent = str ? JSON.parse(str) : [];
        } catch (e) {
            console.warn("[AiChat] Failed to parse web content:", e);
        }
    }

    return {
        thinkingContent: thinkingMatch ? thinkingMatch[1].trim() : "",
        webContent,
        regularContent,
    };
}

/**
 * Render the agent-native timeline: walk `events` in arrival order, emitting
 * a thinking header or tool-call card for each entry. The last streaming
 * thinking entry (no `duration_ms` yet) shows the "思考中…" pulse.
 */
function AgentTimeline({
    events,
    isStreaming,
}: {
    events: AgentEvent[];
    isStreaming: boolean;
}) {
    // Index of the last thinking event that still has no duration — that's
    // the one currently being streamed (drives the pulse animation).
    const openThinkingIdx = (() => {
        for (let i = events.length - 1; i >= 0; i--) {
            const ev = events[i];
            if (ev.type === "thinking" && ev.duration_ms == null) return i;
        }
        return -1;
    })();

    return (
        <>
            {events.map((ev, i) => {
                if (ev.type === "thinking") {
                    return (
                        <AgentThinkingHeader
                            key={`t-${i}`}
                            reasoning={ev.content}
                            durationMs={ev.duration_ms}
                            isStreaming={isStreaming && i === openThinkingIdx}
                        />
                    );
                }
                return (
                    <ToolCallDisplay
                        key={ev.tool_call_id || `tc-${i}`}
                        toolCall={ev}
                    />
                );
            })}
        </>
    );
}

const AiMessageBubble = memo(
    ({
        message,
        isLatest,
        isStreaming,
        onRegenerate,
        siblingIdx,
        siblingCount,
        setSiblingIdx,
        knowledgeChatLayout,
        onOpenCitationPanel,
        activeCitationMessageId,
    }: AiMessageBubbleProps) => {
        const isUser = message.isCreatedByUser;

        if (isUser) {
            return (
                <UserBubble
                    message={message}
                    siblingIdx={siblingIdx}
                    siblingCount={siblingCount}
                    setSiblingIdx={setSiblingIdx}
                    knowledgeChatLayout={knowledgeChatLayout}
                />
            );
        }
        return (
            <AssistantBubble
                message={message}
                isLatest={isLatest}
                isStreaming={isStreaming}
                onRegenerate={onRegenerate}
                siblingIdx={siblingIdx}
                siblingCount={siblingCount}
                setSiblingIdx={setSiblingIdx}
                knowledgeChatLayout={knowledgeChatLayout}
                onOpenCitationPanel={onOpenCitationPanel}
                activeCitationMessageId={activeCitationMessageId}
            />
        );
    }
);

AiMessageBubble.displayName = "AiMessageBubble";

// ==================== User Bubble ====================
function UserBubble({
    message,
    siblingIdx,
    siblingCount,
    setSiblingIdx,
    knowledgeChatLayout,
}: {
    message: ChatMessage;
    siblingIdx?: number;
    siblingCount?: number;
    setSiblingIdx?: (idx: number) => void;
    knowledgeChatLayout?: boolean;
}) {
    const { user } = useAuthContext();

    // Pull out the optional `:::tag {...}:::` chip prefix
    const { tag, bodyText } = useMemo(
        () => parseUserMessageText(message.text || ""),
        [message.text]
    );

    return (
        <div className={cn("flex justify-end py-3", knowledgeChatLayout ? "w-full px-4" : "px-4")}>
            <div className={cn("min-w-0", knowledgeChatLayout ? "max-w-[min(92%,56rem)]" : "max-w-[80%]")}>
                {/* Render uploaded files if any */}
                {message.files && message.files.length > 0 && (
                    <div className="flex flex-wrap gap-2 mb-2 mt-1">
                        {message.files.map((file, i) => {
                            const fileName = file.name || file.file_name || "File";
                            const fileType = getFileTypebyFileName(fileName);
                            const isImage = ["jpg", "jpeg", "png", "bmp", "gif", "webp"].includes(fileType);
                            const fileUrl = file.filepath || file.file_url;

                            if (isImage && fileUrl) {
                                return (
                                    <div key={i} className="flex border bg-white p-1 rounded-xl max-w-sm">
                                        <Image
                                            imagePath={fileUrl}
                                            altText={fileName}
                                            height={100}
                                            width={100}
                                        />
                                    </div>
                                );
                            }

                            return (
                                <div key={i} className="flex items-center gap-2 border bg-white p-2 rounded-xl cursor-pointer hover:bg-gray-50 max-w-sm" onClick={() => fileUrl && window.open(fileUrl, '_blank')}>
                                    <FileIcon type={fileType} className="" />
                                    <div className="overflow-hidden">
                                        <div className="truncate text-sm font-bold" title={fileName}>
                                            {fileName}
                                        </div>
                                        <div className="truncate text-xs text-text-secondary" title={fileName}>
                                            {fileName && getFileTypebyFileName(fileName)}
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
                <div className="flex gap-3">
                    {/* Avatar (hidden by style only) */}
                    <div className="hidden shrink-0 flex justify-center">
                        <Avatar className="w-6 h-6 text-xs">
                            {user?.avatar ? <AvatarImage src={user?.avatar} alt="User" /> : <AvatarName name={user?.username} />}
                        </Avatar>
                    </div>
                    {/* Content */}
                    <div className="flex-1 min-w-0">
                        {/* Name (hidden by style only) */}
                        <div className="hidden rc-name select-none font-semibold text-base">{user?.username}</div>
                        <div
                            className={cn(
                                "px-3 py-2 whitespace-pre-wrap break-words rounded-[8px]",
                                knowledgeChatLayout
                                    ? "bg-[#F2F3F5] text-[#4E5969] text-[14px] leading-[22px]"
                                    : "rounded-[10px] bg-[#E6EDFC] text-[#1d2129] text-sm"
                            )}
                        >
                            {tag && (
                                <span
                                    className={cn(
                                        "mr-1 inline-flex max-w-[min(240px,90%)] shrink-0 items-center rounded-[2px] px-1 align-middle text-[#212121] select-none",
                                        knowledgeChatLayout
                                            ? "text-[14px] font-normal leading-[22px]"
                                            : "h-5 text-xs font-medium leading-none align-middle"
                                    )}
                                    style={{ backgroundColor: "#335CFF59" }}
                                    title={`#${tag.name}`}
                                >
                                    <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
                                        #{tag.name}
                                    </span>
                                </span>
                            )}
                            {bodyText}
                        </div>
                    </div>
                </div>
                {/* Action buttons */}
                <div className="flex items-center justify-end gap-1 mt-1.5">
                    <CopyButton text={tag ? `#${tag.name} ${bodyText}` : message.text} />
                    {siblingIdx !== undefined && siblingCount !== undefined && setSiblingIdx && (
                        <SiblingSwitch siblingIdx={siblingIdx} siblingCount={siblingCount} setSiblingIdx={setSiblingIdx} />
                    )}
                </div>
            </div>
        </div>
    );
}

// ==================== Assistant Bubble ====================
function AssistantBubble({
    message,
    isLatest,
    isStreaming,
    onRegenerate,
    siblingIdx,
    siblingCount,
    setSiblingIdx,
    knowledgeChatLayout,
    onOpenCitationPanel,
    activeCitationMessageId,
}: {
    message: ChatMessage;
    isLatest?: boolean;
    isStreaming?: boolean;
    onRegenerate?: () => void;
    siblingIdx?: number;
    siblingCount?: number;
    setSiblingIdx?: (idx: number) => void;
    knowledgeChatLayout?: boolean;
    onOpenCitationPanel?: (payload: CitationReferencesDesktopPayload) => void;
    activeCitationMessageId?: string | null;
}) {
    // v2.5 Agent-native detection — when a message has structured fields set
    // (populated by useAiChatSSE.onAgentUpdate or by getAgentMessages history
    // loader), skip the legacy :::thinking:::/:::web::: regex parsing and let
    // the dedicated components own those sections.
    const isAgentNative = useMemo(() => {
        if (message.category === "agent_answer") return true;
        return Array.isArray(message.events) && message.events.length > 0;
    }, [message.category, message.events]);

    // Parse :::thinking::: and :::web::: from the raw text (legacy path only).
    // Agent-native path still needs to strip the legacy envelope because the
    // SSE hook keeps writing `:::thinking…:::\n> ⏳/✅` status lines into
    // `text` for backward compat — rendering them here would duplicate the
    // thinking header + tool call cards in the message body.
    const { thinkingContent, webContent, regularContent } = useMemo(() => {
        if (isAgentNative) {
            const raw = message.text || "";
            const stripped = raw
                .replace(/:::thinking[\s\S]*?:::/g, "")
                .replace(/^>\s*[⏳✅⚠️][^\n]*\n?/gm, "")
                .trimStart();
            return { thinkingContent: "", webContent: [], regularContent: stripped };
        }
        return parseMessageText(message.text || "");
    }, [message.text, isAgentNative]);
    const { data: bsConfig } = useGetBsConfig()
    const sourceRef = useRef<any>(null);

    const modelName = message.sender || "AI";
    const showCursor = isLatest && isStreaming;
    const isWaitingFirstToken =
        isStreaming &&
        isLatest &&
        !message.error &&
        !regularContent &&
        !thinkingContent &&
        webContent.length === 0;

    // Show a "等待模型响应…" pill while the request is in flight but no
    // tokens / events have landed yet. Disappears as soon as anything
    // streams in (events.length > 0 || regularContent).
    const showWaiting =
        !!isStreaming &&
        !!isLatest &&
        !message.error &&
        !regularContent &&
        !(Array.isArray(message.events) && message.events.length > 0);

    return (
        <div className={cn("flex justify-start py-3", knowledgeChatLayout ? "w-full px-4" : "px-4")}>
            <div className={cn("min-w-0", knowledgeChatLayout ? "w-full max-w-none" : "max-w-[80%]")}>
                {/* Avatar + name kept but hidden via style only */}
                <div className="hidden gap-3">
                    <div className="shrink-0 w-6 h-6 rounded-full flex items-center justify-center">
                        {bsConfig?.assistantIcon.image ? <img src={__APP_ENV__.BASE_URL + bsConfig?.assistantIcon.image} alt="" />
                            : <BotIcon size={16} className="text-black" />}
                    </div>
                    <div className="model-name select-none font-semibold text-base">{modelName}</div>
                </div>

                {/* Pre-stream "等待模型响应…" pill — same shape as the thinking
                    header so it doesn't visually jump when it's replaced. */}
                {showWaiting && (
                    <div className="mt-3 inline-flex w-fit items-center justify-center gap-1.5 rounded-xl bg-surface-tertiary px-3 py-2 text-xs leading-[18px] text-text-secondary">
                        <Loader2 className="size-3.5 animate-spin" />
                        <span>thinking…</span>
                    </div>
                )}

                {/* v2.5 Agent-native rendering: ordered events (thinking + tool calls) */}
                {isAgentNative ? (
                    <AgentTimeline
                        events={message.events || []}
                        isStreaming={!!isStreaming && isLatest}
                    />
                ) : (
                    <>
                        {/* Legacy :::thinking::: reuse Thinking component */}
                        {thinkingContent && <Thinking>{thinkingContent}</Thinking>}
                        {/* Legacy :::web::: → SearchWebUrls */}
                        {webContent.length > 0 && <SearchWebUrls webs={webContent} />}
                    </>
                )}

                {/* Error state */}
                {showWaiting ? null : message.error ? (
                    <div
                        className={cn(
                            "text-red-500 bg-red-50 px-3 py-2",
                            knowledgeChatLayout
                                ? "rounded-[2px] text-[14px] leading-[22px]"
                                : "text-sm rounded-[10px]"
                        )}
                    >
                        {regularContent || "发生错误，请重试"}
                    </div>
                ) : (
                    /* Main content — uses existing Markdown with citation support */
                    <div
                        className={cn(
                            "bs-mkdown message-content overflow-hidden break-words [word-break:break-all]",
                            knowledgeChatLayout
                                ? "rounded-[2px] border-0 bg-transparent px-0 py-1 text-[14px] leading-[22px] [--markdown-font-size:14px]"
                                : "rounded-[10px] bg-white border border-[#E5E6EB] px-3 py-2 text-sm"
                        )}
                    >

                        {isWaitingFirstToken ? (
                            <div className="flex items-center py-0.5" aria-label="AI 正在思考">
                                <span className="inline-block w-3 h-3 rounded-full bg-black animate-pulse-scale" />
                            </div>
                        ) : (
                        <Markdown
                            content={regularContent}
                            webContent={webContent}
                            citations={message.citations}
                            showCursor={showCursor}
                            isLatestMessage={!!isLatest}
                        />
                        )}
                    </div>
                )}

                {/* Action buttons (only show when not streaming) */}
                {!isStreaming && regularContent && (
                    <div className="flex items-center gap-1 mt-1.5 text-gray-400">
                        <CitationReferencesDrawer
                            content={regularContent}
                            webContent={webContent}
                            citations={message.citations}
                            messageId={message.messageId}
                            desktopMode="inline-panel"
                            open={activeCitationMessageId === message.messageId}
                            onOpenChange={(nextOpen) => {
                                if (!nextOpen && activeCitationMessageId === message.messageId) {
                                    onOpenCitationPanel?.({
                                        messageId: message.messageId,
                                        content: regularContent,
                                        webContent,
                                        citations: message.citations,
                                        referenceItems: [],
                                    });
                                }
                            }}
                            onDesktopOpen={onOpenCitationPanel}
                            actionButtons={
                                <>
                                    <CopyButton text={regularContent} />
                                    {onRegenerate && (
                                        <button
                                            type="button"
                                            onClick={(event) => {
                                                event.preventDefault();
                                                event.stopPropagation();
                                                onRegenerate();
                                            }}
                                            className="flex size-6 items-center justify-center rounded-[6px] backdrop-blur-[4px] transition-colors hover:bg-[#F7F7F7]"
                                            title="刷新"
                                            aria-label="刷新"
                                        >
                                            <RefreshCwIcon size={14} className="text-[#818181]" />
                                        </button>
                                    )}
                                    <TextToSpeechButton
                                        className="flex size-6 items-center justify-center rounded-[6px] backdrop-blur-[4px] transition-colors hover:bg-[#F7F7F7]"
                                        messageId={message.messageId || ""}
                                        text={regularContent}
                                    />
                                </>
                            }
                        />
                        {/* Reference Sources */}
                        {message.source !== 0 && (
                            <div className="mr-2 pt-0.5">
                                <MessageSource
                                    extra={null}
                                    end={true}
                                    source={message.source}
                                    onSource={() => {
                                        sourceRef.current?.openModal({
                                            messageId: message.messageId || "",
                                            message: regularContent,
                                            chatId: message.conversationId,
                                        });
                                    }}
                                />
                            </div>
                        )}
                        {/* Sibling paging */}
                        {siblingIdx !== undefined && siblingCount !== undefined && setSiblingIdx && (
                            <SiblingSwitch siblingIdx={siblingIdx} siblingCount={siblingCount} setSiblingIdx={setSiblingIdx} />
                        )}
                    </div>
                )}
                <ResouceModal ref={sourceRef} />
            </div>
        </div>
    );
}

export default AiMessageBubble;
