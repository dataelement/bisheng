/**
 * Single message bubble for user / assistant messages.
 */
import {
    BotIcon,
    ChevronLeftIcon,
    ChevronRightIcon,
    Loader2,
    RefreshCwIcon
} from "lucide-react";
import { Outlined } from "bisheng-icons";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import DeepThinkingGroup from "~/components/Chat/Messages/DeepThinkingGroup";
import ThinkingContent from "~/components/Chat/Messages/ThinkingContent";
import { groupEventsForDisplay, type DisplayBlock } from "~/components/Chat/Messages/groupEvents";
import ToolCallDisplay from "~/components/Chat/Messages/ToolCallDisplay";
import Markdown from "~/components/Chat/Messages/Content/Markdown";
import CitationReferencesDrawer, { type CitationReferencesDesktopPayload } from "~/components/Chat/Messages/Content/CitationReferencesDrawer";
import SearchWebUrls from "~/components/Chat/Messages/Content/SearchWebUrls";
import { TaskTurnPanel } from "~/components/Linsight/Execution/TaskTurnPanel";
import type { ArtifactFile } from "~/components/Linsight/Artifacts/artifactUtils";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
import { TextToSpeechButton } from "~/components/Voice/TextToSpeechButton";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import { useAuthContext } from "~/hooks";
import { useMessageSelection } from "~/hooks/useMessageSelection";
import {
    ExportSelectionButton,
    MessageCheckbox,
} from "~/components/Chat/MessageSelection";
import { copyText, cn } from "~/utils";
import type { AgentEvent, ChatMessage } from "~/api/chatApi";
import { getFileTypebyFileName } from "~/components/ui/icon/File/FileIcon";

// Map an uploaded file's extension to a bisheng outlined file-type icon.
// Anything not listed falls back to the generic Outlined.File icon.
const FILE_TYPE_ICONS: Record<string, typeof Outlined.File> = {
    // FileExcel
    xls: Outlined.FileExcel,
    xlsx: Outlined.FileExcel,
    csv: Outlined.FileExcel,
    et: Outlined.FileExcel,
    // FilePdf
    pdf: Outlined.FilePdf,
    ppt: Outlined.FilePdf,
    dps: Outlined.FilePdf,
    // FileTxt
    txt: Outlined.FileTxt,
    // FileWord
    doc: Outlined.FileWord,
    docx: Outlined.FileWord,
    wps: Outlined.FileWord,
    // FileImage
    png: Outlined.FileImage,
    jpg: Outlined.FileImage,
    jpeg: Outlined.FileImage,
    bmp: Outlined.FileImage,
    // FileEditing
    md: Outlined.FileEditing,
    // File (generic)
    html: Outlined.File,
};

/**
 * Uploaded-file list for a user message: a type icon + filename per row, never a
 * content preview. Stacks vertically and scrolls past 120px. A linear-gradient
 * mask softly fades the top/bottom edge (instead of a hard clip) whenever there
 * is more content to scroll in that direction — same fade trick used elsewhere.
 */
function UploadedFileList({ files }: { files: any[] }) {
    const scrollRef = useRef<HTMLDivElement>(null);
    const [fade, setFade] = useState({ top: false, bottom: false });

    const updateFade = useCallback(() => {
        const el = scrollRef.current;
        if (!el) return;
        const top = el.scrollTop > 0;
        const bottom = el.scrollTop + el.clientHeight < el.scrollHeight - 1;
        setFade((prev) => (prev.top === top && prev.bottom === bottom ? prev : { top, bottom }));
    }, []);

    useEffect(() => {
        updateFade();
    }, [files, updateFade]);

    const maskStyle = useMemo(() => {
        if (!fade.top && !fade.bottom) return undefined;
        const topStop = fade.top ? "16px" : "0";
        const bottomStop = fade.bottom ? "calc(100% - 16px)" : "100%";
        const value = `linear-gradient(to bottom, transparent, #000 ${topStop}, #000 ${bottomStop}, transparent)`;
        return { maskImage: value, WebkitMaskImage: value };
    }, [fade]);

    if (!files || files.length === 0) return null;

    return (
        <div
            ref={scrollRef}
            onScroll={updateFade}
            style={maskStyle}
            className="scrollbar-os mb-2 mt-1 flex max-h-[120px] max-w-sm flex-col gap-3 overflow-y-auto"
        >
            {files.map((file, i) => {
                const fileName = file.name || file.file_name || "File";
                const fileType = getFileTypebyFileName(fileName);
                const FileTypeIcon = FILE_TYPE_ICONS[fileType] ?? Outlined.File;
                return (
                    <div key={i} className="flex shrink-0 items-center gap-1 text-[#999999]">
                        <FileTypeIcon size={12} className="shrink-0 text-[#CCCCCC]" />
                        <div className="min-w-0 flex-1 overflow-hidden">
                            <div className="truncate text-xs" title={fileName}>
                                {fileName}
                            </div>
                        </div>
                    </div>
                );
            })}
        </div>
    );
}

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
    /** F035: preview a task-turn document in the inline workspace panel (ChatView
        owns it) — a conversation doc link opens the file directly, no drawer. */
    onPreviewFile?: (file: ArtifactFile) => void;
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
            {copied ? <Outlined.Copied size={14} className="text-blue-500" /> : <Outlined.Copy size={14} className="text-[#818181]" />}
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
 * Render the agent-native timeline: walk `events` as display blocks and emit
 * a `DeepThinkingGroup` per non-text run + a lightweight `<Markdown>` per
 * intermediate text block. The LAST text block (if events ends with text)
 * is rendered separately by the bubble's main `<Markdown>` body so that
 * citations / copy / voice still attach to the final answer.
 */
function AgentTimeline({
    events,
    isStreaming,
    finalTextIdx,
    messageId,
}: {
    events: AgentEvent[];
    /** Whether the message is still streaming — used to mark the trailing group
     * as live so its thinking node shows the 正在/已 status. */
    isStreaming: boolean;
    /** Index in `blocks` of the trailing text block to skip (rendered by the
     * main bubble Markdown). -1 if no such block. */
    finalTextIdx: number;
    /** Bubble's message id, used to namespace intermediate Markdown blocks. */
    messageId: string;
}) {
    const blocks: DisplayBlock[] = groupEventsForDisplay(events);
    const lastGroupIdx = (() => {
        for (let i = blocks.length - 1; i >= 0; i--) {
            if (blocks[i].kind === "group") return i;
        }
        return -1;
    })();

    return (
        <div className="flex w-full min-w-0 flex-col gap-3">
            {blocks.map((block, i) => {
                if (block.kind === "text") {
                    if (i === finalTextIdx) return null;
                    return (
                        <Markdown
                            key={`text-${i}`}
                            content={block.content}
                            webContent={[]}
                            citations={undefined}
                            messageId={`${messageId}-intermediate-${i}`}
                            showCursor={false}
                            isLatestMessage={false}
                        />
                    );
                }
                return (
                    <DeepThinkingGroup
                        key={`grp-${i}`}
                        events={block.events}
                        isStreaming={isStreaming && i === lastGroupIdx && finalTextIdx === -1}
                    />
                );
            })}
        </div>
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
        onPreviewFile,
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
                onPreviewFile={onPreviewFile}
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

    // F028: render selection checkbox at the left margin when selection mode
    // is active for this conversation. ``mr-auto`` keeps the user bubble
    // right-aligned regardless of whether the checkbox is mounted.
    const { isActiveForChat } = useMessageSelection();
    const showCheckbox =
        !!message.conversationId &&
        isActiveForChat(message.conversationId);

    // Pull out the optional `:::tag {...}:::` chip prefix
    const { tag, bodyText } = useMemo(
        () => parseUserMessageText(message.text || ""),
        [message.text]
    );

    return (
        <div className={cn("flex justify-end py-3 items-start gap-2", knowledgeChatLayout ? "w-full px-0" : "px-4")}>
            {showCheckbox && message.conversationId && (
                <MessageCheckbox
                    chatId={message.conversationId}
                    messageId={message.messageId}
                    className="mr-auto mt-2 shrink-0"
                />
            )}
            <div className={cn("flex min-w-0 flex-col items-end", knowledgeChatLayout ? "max-w-[min(92%,56rem)]" : "max-w-[80%]")}>
                {/* Uploaded files: icon + filename only (no preview), with soft fade
                    edges while scrolling so the 120px-clipped list never hard-cuts. */}
                <UploadedFileList files={message.files || []} />
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
                                // w-fit: the text bubble hugs its own content and stays
                                // independent of the (possibly wider) file card above it.
                                "w-fit max-w-full px-3 py-2 whitespace-pre-wrap break-words rounded-[8px]",
                                knowledgeChatLayout
                                    ? "bg-[#F2F3F5] text-[#4E5969] text-[14px] leading-[22px]"
                                    : "rounded-[10px] bg-blue-500/[0.07] text-[#1d2129] text-sm"
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
                                    style={{ backgroundColor: "rgb(var(--brand-500)/0.35)" }}
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
    onPreviewFile,
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
    onPreviewFile?: (file: ArtifactFile) => void;
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
    const { thinkingContent, webContent, regularContent, finalTextIdx } = useMemo(() => {
        if (isAgentNative) {
            const evs = message.events ?? [];
            const blocks = groupEventsForDisplay(evs);

            // New format: events array contains text items. The "final" body
            // is rendered by the main <Markdown> outside the timeline ONLY
            // when events end with a text block. Any non-trailing text block
            // (mid-stream ReAct: text → tool → text) renders inline inside
            // the timeline.
            const last = blocks[blocks.length - 1];
            if (last && last.kind === "text") {
                return {
                    thinkingContent: "",
                    webContent: [],
                    regularContent: last.content,
                    finalTextIdx: blocks.length - 1,
                };
            }

            // Legacy: events without text items. Strip the legacy envelope
            // out of message.text and use that as the body (today's behaviour).
            const raw = message.text || "";
            const stripped = raw
                .replace(/:::thinking[\s\S]*?:::/g, "")
                .replace(/^>\s*[⏳✅⚠️][^\n]*\n?/gm, "")
                .trimStart();
            return {
                thinkingContent: "",
                webContent: [],
                regularContent: stripped,
                finalTextIdx: -1,
            };
        }
        return { ...parseMessageText(message.text || ""), finalTextIdx: -1 };
    }, [message.text, message.events, isAgentNative]);
    const { data: bsConfig } = useGetBsConfig()

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

    // F028: per-message selection checkbox.
    const { isActiveForChat } = useMessageSelection();
    const showCheckbox =
        !!message.conversationId &&
        isActiveForChat(message.conversationId);

    // F035 Track J (TJ-7): task turn — render the embedded linsight execution
    // panel by SV instead of the agent/legacy text rendering. The user question
    // bubble is the preceding (daily) user row; this row owns the rich panel.
    if (message.category === "task") {
        return (
            <div className={cn("flex justify-start py-3 items-start gap-2", knowledgeChatLayout ? "w-full px-0" : "px-4")}>
                {showCheckbox && message.conversationId && (
                    <MessageCheckbox
                        chatId={message.conversationId}
                        messageId={message.messageId}
                        className="mt-2 shrink-0"
                    />
                )}
                <div className={cn("min-w-0", knowledgeChatLayout ? "w-full max-w-none" : "max-w-[80%]")}>
                    <TaskTurnPanel
                        versionId={message.linsightSessionVersionId || ""}
                        conversationId={message.conversationId}
                        answer={message.text}
                        onPreviewFile={onPreviewFile}
                    />
                </div>
            </div>
        );
    }

    return (
        <div className={cn("flex justify-start py-3 items-start gap-2", knowledgeChatLayout ? "w-full px-0" : "px-4")}>
            {showCheckbox && message.conversationId && (
                <MessageCheckbox
                    chatId={message.conversationId}
                    messageId={message.messageId}
                    className="mt-2 shrink-0"
                />
            )}
            <div className={cn("min-w-0", knowledgeChatLayout ? "w-full max-w-none" : "max-w-[80%]")}>
                {/* Avatar + name kept but hidden via style only */}
                <div className="hidden gap-3">
                    <div className="shrink-0 w-6 h-6 rounded-full flex items-center justify-center">
                        {bsConfig?.assistantIcon.image ? <img src={__APP_ENV__.BASE_URL + bsConfig?.assistantIcon.image} alt="" />
                            : <BotIcon size={16} className="text-black" />}
                    </div>
                    <div className="model-name select-none font-semibold text-base">{modelName}</div>
                </div>

                {/* v2.5 Agent-native rendering: ordered events (thinking + tool calls) */}
                {isAgentNative ? (
                    <div className="mb-3 w-full min-w-0">
                        <AgentTimeline
                            events={message.events || []}
                            isStreaming={Boolean(isStreaming && isLatest)}
                            finalTextIdx={finalTextIdx}
                            messageId={message.messageId}
                        />
                    </div>
                ) : (
                    <>
                        {/* Legacy :::thinking::: — render with the same "思考内容" block as the
                            agent-native timeline (Messages/ThinkingContent) so reasoning looks
                            identical across the homepage chat and the knowledge/file/article docks. */}
                        {thinkingContent && (
                            <div className="mb-3 w-full min-w-0">
                                <ThinkingContent reasoning={thinkingContent} />
                            </div>
                        )}
                        {/* Legacy :::web::: → SearchWebUrls */}
                        {webContent.length > 0 && <SearchWebUrls webs={webContent} />}
                    </>
                )}

                {/* Pre-stream "正在思考" indicator — pulsing black dot. Rendered AFTER the
                    thinking block so that once "思考内容" appears it sits below that node
                    (answer-pending), not above it. */}
                {showWaiting && (
                    <div className="flex items-center py-0.5" aria-label="AI 正在思考">
                        <span className="inline-block w-3 h-3 rounded-full bg-black animate-pulse-scale" />
                    </div>
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
                                messageId={message.messageId}
                                onOpenCitationPanel={onOpenCitationPanel}
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
                            desktopMode={onOpenCitationPanel ? "inline-panel" : "overlay"}
                            open={onOpenCitationPanel ? activeCitationMessageId === message.messageId : undefined}
                            onOpenChange={onOpenCitationPanel ? ((nextOpen) => {
                                if (!nextOpen && activeCitationMessageId === message.messageId) {
                                    onOpenCitationPanel({
                                        messageId: message.messageId,
                                        content: regularContent,
                                        webContent,
                                        citations: message.citations,
                                        referenceItems: [],
                                    });
                                }
                            }) : undefined}
                            onDesktopOpen={onOpenCitationPanel}
                            actionButtons={
                                <>
                                    <CopyButton text={regularContent} />
                                    {/* Export is only offered in the full homepage chat — the lightweight
                                        knowledge/file/article docks (knowledgeChatLayout) hide it. */}
                                    {!knowledgeChatLayout && message.conversationId && message.messageId && (
                                        <ExportSelectionButton
                                            chatId={message.conversationId}
                                            messageId={message.messageId}
                                        />
                                    )}
                                    <TextToSpeechButton
                                        className="flex size-6 items-center justify-center rounded-[6px] backdrop-blur-[4px] transition-colors hover:bg-[#F7F7F7]"
                                        messageId={message.messageId || ""}
                                        text={regularContent}
                                    />
                                </>
                            }
                        />
                        {/* Sibling paging */}
                        {siblingIdx !== undefined && siblingCount !== undefined && setSiblingIdx && (
                            <SiblingSwitch siblingIdx={siblingIdx} siblingCount={siblingCount} setSiblingIdx={setSiblingIdx} />
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}

export default AiMessageBubble;
