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
import { ChatErrorCard, isTransientErrorType } from "~/components/ChatErrorCard";
import { MessageFeedbackButtons } from "~/components/Chat/MessageFeedbackButtons";
import { likeChatApi, disLikeCommentApi } from "~/api/apps";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import { useAuthContext, useLocalize } from "~/hooks";
import { useMessageSelection } from "~/hooks/useMessageSelection";
import {
    ExportSelectionButton,
    MessageCheckbox,
} from "~/components/Chat/MessageSelection";
import { copyText, cn } from "~/utils";
import type { AgentEvent, ChatMessage } from "~/api/chatApi";
import { getFileTypeIcon, isImageFileName } from "~/components/ui/icon/File/FileIcon";
import { MessageImage } from "~/components/Chat/Messages/Content/MessageImage";
import { getRecoveryModelCandidates } from "~/components/modelRateLimitRecoveryDialogHelpers";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common/types";
import { useModelRateLimitRecovery } from "~/hooks/useModelRateLimitRecovery";
import type {
    ModelRecoveryCommand,
    ModelRecoveryResponse,
    ModelRecoveryTarget,
} from "~/api/modelRecovery";
import { resolveDisplayedModelRateLimitState } from "~/hooks/queries/endpoints/modelRateLimitPolling";

// Transient/retryable backend error codes surfaced by daily-mode chat — LLM rate
// limit (12046), generic busy (429/503), thread-pool full (10540), dept concurrency
// (12045). Only consulted when the envelope carried no `error_type` (an older
// backend, or a domain error that doesn't classify itself): a retryable code still
// has to reach the calm "busy" card rather than the red failure one.
const RETRYABLE_ERROR_CODES = new Set([12046, 429, 503, 10540, 12045]);

/**
 * Uploaded-file list for a user message: a type icon + filename per row, never a
 * content preview. Stacks vertically and scrolls past 120px. A linear-gradient
 * mask softly fades the top/bottom edge (instead of a hard clip) whenever there
 * is more content to scroll in that direction — same fade trick used elsewhere.
 */
function UploadedFileList({ files, conversationId }: { files: any[]; conversationId?: string }) {
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

    // Pictures are shown as pictures; everything else keeps the compact
    // icon+name row it always had.
    const images = files.filter((f) => isImageFileName(f.name || f.file_name));
    const others = files.filter((f) => !isImageFileName(f.name || f.file_name));

    return (
        <>
            {images.length > 0 && (
                <div className="mb-2 mt-1 flex flex-wrap justify-end gap-2">
                    {images.map((file, i) => (
                        <MessageImage
                            key={file.file_id ?? i}
                            conversationId={conversationId}
                            fileId={file.file_id}
                            altText={file.name || file.file_name}
                            initialUrl={file.filepath || file.file_path || file.file_url}
                        />
                    ))}
                </div>
            )}
            {others.length > 0 && (
                <div
                    ref={scrollRef}
                    onScroll={updateFade}
                    style={maskStyle}
                    className="scrollbar-os mb-2 mt-1 flex max-h-[120px] max-w-sm flex-col gap-3 overflow-y-auto"
                >
                    {others.map((file, i) => {
                        const fileName = file.name || file.file_name || "File";
                        const FileTypeIcon = getFileTypeIcon(fileName);
                        return (
                            <div key={i} className="flex shrink-0 items-center gap-1 text-text-3">
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
            )}
        </>
    );
}

interface AiMessageBubbleProps {
    message: ChatMessage;
    isLatest?: boolean;
    isStreaming?: boolean;
    onRegenerate?: () => void;
    onRecover?: (command: ModelRecoveryCommand) => Promise<ModelRecoveryResponse>;
    onRecoveryModelChange?: (modelId: string, modelName: string) => void;
    // Sibling paging
    siblingIdx?: number;
    siblingCount?: number;
    setSiblingIdx?: (idx: number) => void;
    /** Knowledge space AI: gray user bubble, borderless assistant, 14px body, full width */
    knowledgeChatLayout?: boolean;
    /** Show the export-session entry under assistant messages. Only the full
        homepage/task chat opts in; the lightweight knowledge/file/article docks
        and the share view leave it off. */
    allowExport?: boolean;
    /** Show the 点赞/点踩 feedback buttons under assistant answers. Default true;
        the read-only anonymous share view passes false. */
    allowFeedback?: boolean;
    onOpenCitationPanel?: (payload: CitationReferencesDesktopPayload) => void;
    activeCitationMessageId?: string | null;
    /** F035: preview a task-turn document in the inline workspace panel (ChatView
        owns it) — a conversation doc link opens the file directly, no drawer. */
    onPreviewFile?: (file: ArtifactFile) => void;
}

// --- Copy button with feedback ---
function CopyButton({ text }: { text: string }) {
    const localize = useLocalize();
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
            className="flex size-6 items-center justify-center rounded-md transition-colors hover:bg-fill-1"
            title={localize('com_ui_copy')}
            aria-label={localize('com_ui_copy')}
        >
            {copied ? <Outlined.Copied size={14} className="text-blue-500" /> : <Outlined.Copy size={14} className="text-text-3" />}
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
        onRecover,
        onRecoveryModelChange,
        siblingIdx,
        siblingCount,
        setSiblingIdx,
        knowledgeChatLayout,
        allowExport,
        allowFeedback = true,
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
                onRecover={onRecover}
                onRecoveryModelChange={onRecoveryModelChange}
                siblingIdx={siblingIdx}
                siblingCount={siblingCount}
                setSiblingIdx={setSiblingIdx}
                knowledgeChatLayout={knowledgeChatLayout}
                allowExport={allowExport}
                allowFeedback={allowFeedback}
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
            {/* Mobile: cap the bubble so its left edge keeps a 40px gap from the
                content area (long URLs were overflowing off the left edge). */}
            <div className={cn("flex min-w-0 flex-col items-end touch-mobile:max-w-[calc(100%-40px)]", knowledgeChatLayout ? "max-w-[min(92%,56rem)]" : "max-w-[80%]")}>
                {/* Uploaded files: icon + filename only (no preview), with soft fade
                    edges while scrolling so the 120px-clipped list never hard-cuts. */}
                <UploadedFileList files={message.files || []} conversationId={message.conversationId} />
                {/* min-w-0: without it this flex row's `min-width: auto` floors at
                    the URL's (unbreakable) min-content width, defeating the bubble's
                    max-width and letting long content overflow off the left edge. */}
                <div className="flex min-w-0 gap-3">
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
                                // overflow-wrap:anywhere (not break-words): break-word
                                // doesn't shrink min-content, so w-fit/fit-content keeps
                                // sizing the box to a long unbreakable URL and max-width
                                // can't clamp it — `anywhere` reduces min-content so the
                                // box shrinks and the URL wraps inside max-w-full.
                                "w-fit max-w-full px-3 py-2 whitespace-pre-wrap [overflow-wrap:anywhere] rounded-lg",
                                knowledgeChatLayout
                                    ? "bg-fill-2 text-text-2 text-[14px] leading-[22px]"
                                    : "rounded-[10px] bg-blue-500/[0.07] text-text-1 text-sm"
                            )}
                        >
                            {tag && (
                                <span
                                    className={cn(
                                        "mr-1 inline-flex max-w-[min(240px,90%)] shrink-0 items-center rounded-[2px] px-1 align-middle text-text-1 select-none",
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
    onRecover,
    onRecoveryModelChange,
    siblingIdx,
    siblingCount,
    setSiblingIdx,
    knowledgeChatLayout,
    allowExport,
    allowFeedback = true,
    onOpenCitationPanel,
    activeCitationMessageId,
    onPreviewFile,
}: {
    message: ChatMessage;
    isLatest?: boolean;
    isStreaming?: boolean;
    onRegenerate?: () => void;
    onRecover?: (command: ModelRecoveryCommand) => Promise<ModelRecoveryResponse>;
    onRecoveryModelChange?: (modelId: string, modelName: string) => void;
    siblingIdx?: number;
    siblingCount?: number;
    setSiblingIdx?: (idx: number) => void;
    knowledgeChatLayout?: boolean;
    allowExport?: boolean;
    allowFeedback?: boolean;
    onOpenCitationPanel?: (payload: CitationReferencesDesktopPayload) => void;
    activeCitationMessageId?: string | null;
    onPreviewFile?: (file: ArtifactFile) => void;
}) {
    const localize = useLocalize();
    const recoveryTransport = useCallback(
        (_target: ModelRecoveryTarget, command: ModelRecoveryCommand) => (
            onRecover?.(command) ?? Promise.resolve({
                execution_id: command.executionId,
                attempt_id: command.attemptId,
                accepted: false,
            })
        ),
        [onRecover],
    );
    const recovery = useModelRateLimitRecovery({
        target: { entry: 'daily' },
        executionId: message.executionId,
        subjectId: message.recoverySubjectId,
        activeAttemptId: message.attemptId,
        currentModelId: message.modelId,
        transport: recoveryTransport,
    });

    // Prefer the backend's own classification; fall back to the status code so
    // pre-classification backends still split busy-vs-failed correctly, and land
    // on the chat-flavoured generic copy when neither says anything.
    const resolvedErrorType = message.errorType
        || (message.errorCode !== undefined && RETRYABLE_ERROR_CODES.has(message.errorCode)
            ? "rate_limit"
            : "chat_unknown");
    // recovery_rejected = still rate-limited after a retry: same recovery
    // affordances (retry / switch model) as the rate_limit card itself.
    const canRecoverRateLimit = (resolvedErrorType === 'rate_limit' || resolvedErrorType === 'recovery_rejected')
        && message.unfinished === true
        && isLatest === true
        && !!message.executionId
        && !!message.recoverySubjectId
        && !!onRecover;

    // A transient/retryable failure (rate limit / busy) renders as the calm neutral
    // notice + Retry instead of the red error card.
    const isTransientError = !!message.error && isTransientErrorType(resolvedErrorType);

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

    // True only when `regularContent` came from the events timeline's trailing
    // text block — i.e. it is a real answer the model streamed in. Every other
    // path falls back to `message.text`, which `onError` overwrites with the
    // error copy, so `regularContent` alone can't tell answer from error text.
    const hasAnswerBody = finalTextIdx >= 0 && !!regularContent;

    // What the failure notice says. When an answer body survived, the specific
    // provider error is noise — what matters is that the answer is cut short.
    const errorNotice = hasAnswerBody
        ? localize("workstation.chat.answer_interrupted")
        : message.errorText || regularContent || localize("workstation.chat.answer_failed");

    const { data: bsConfig } = useGetBsConfig()
    const displayedRateLimitState = resolveDisplayedModelRateLimitState(
        bsConfig?.models,
        message.modelId,
        message.rateLimitState,
    );

    // The always-visible switch list excludes the current and busy models.
    // Picking an item immediately updates the input selector and starts recovery.
    const { showToast } = useToastContext();
    const switchModelOptions = useMemo(
        () => getRecoveryModelCandidates(bsConfig?.models ?? [], message.modelId ?? ''),
        [bsConfig?.models, message.modelId],
    );
    const handleSwitchModel = useCallback(async (targetModelId: string) => {
        const selectedModel = bsConfig?.models.find(
            (model) => String(model.id) === String(targetModelId),
        );
        onRecoveryModelChange?.(
            targetModelId,
            selectedModel?.displayName || selectedModel?.name || '',
        );
        try {
            const result = await recovery.switchModel(targetModelId);
            if (result?.accepted === false) {
                showToast?.({ message: localize('com_message.switch_rejected'), severity: NotificationSeverity.ERROR });
            }
        } catch {
            showToast?.({ message: localize('com_message.switch_rejected'), severity: NotificationSeverity.ERROR });
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps -- localize is identity-unstable (see client AGENTS pitfalls)
    }, [bsConfig?.models, onRecoveryModelChange, recovery.switchModel, showToast]);

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
                        liked={message.liked}
                        allowFeedback={allowFeedback}
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
                    <div className="flex items-center py-0.5" aria-label={localize('com_ui_ai_thinking')}>
                        <span className="inline-block w-3 h-3 rounded-full bg-black animate-pulse-scale" />
                    </div>
                )}

                {/* Main content — uses existing Markdown with citation support.
                    Rendered even when the turn carries an error, as long as a real
                    answer body streamed in: a stream that fails *after* emitting text
                    must keep its markdown + citation rendering instead of degrading to
                    raw text (which also leaks the private-use citation markers). */}
                {!showWaiting && (hasAnswerBody || !message.error) && (
                    <div
                        className={cn(
                            "bs-mkdown message-content overflow-hidden break-words [word-break:break-all]",
                            knowledgeChatLayout
                                ? "rounded-[2px] border-0 bg-transparent px-0 py-1 text-[14px] leading-[22px] [--markdown-font-size:14px]"
                                : "rounded-[10px] bg-white border border-border-base px-3 py-2 text-sm"
                        )}
                    >

                        {isWaitingFirstToken ? (
                            <div className="flex items-center py-0.5" aria-label={localize('com_ui_ai_thinking')}>
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

                {/* Error state — replaces the body when nothing streamed in, and sits
                    below it when a partial answer did. Same card as task mode:
                    localized title + explanation + hint, with the upstream text
                    (which file, which service, what it actually said) behind
                    "view details"; transient hiccups render as the calm notice +
                    Retry, terminal ones as the red card. */}
                {!showWaiting && message.error && (
                    <div className={cn(hasAnswerBody && "mt-2")}>
                        <ChatErrorCard
                            errorType={resolvedErrorType}
                            detail={message.errorDetail}
                            fallbackMessage={errorNotice}
                            onRetry={
                                canRecoverRateLimit
                                    ? recovery.retry
                                    : resolvedErrorType !== 'rate_limit' && isTransientError
                                        ? onRegenerate
                                        : undefined
                            }
                            retrying={recovery.pending}
                            rateLimitState={displayedRateLimitState}
                            onSwitchModel={canRecoverRateLimit ? handleSwitchModel : undefined}
                            switchModelOptions={switchModelOptions}
                        />
                    </div>
                )}

                {/* Action buttons (only show when not streaming). Suppressed on the
                    transient busy notice — copy/feedback on a "try again" status is
                    meaningless; the notice carries its own Retry. */}
                {!isStreaming && regularContent && !isTransientError && (
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
                                    {/* Export is only offered where the host opts in via allowExport
                                        (the full homepage/task chat). The lightweight knowledge/file/
                                        article docks and the share view leave it off. */}
                                    {allowExport && message.conversationId && message.messageId && (
                                        <ExportSelectionButton
                                            chatId={message.conversationId}
                                            messageId={message.messageId}
                                        />
                                    )}
                                    <TextToSpeechButton
                                        className="flex size-6 items-center justify-center rounded-md transition-colors hover:bg-fill-1"
                                        messageId={message.messageId || ""}
                                        text={regularContent}
                                    />
                                    {/* 点赞/点踩 — the answer persists as a chatmessage row, so
                                        reuse the existing /liked + /chat/comment endpoints keyed
                                        by message_id. Hidden on the read-only share view. */}
                                    {allowFeedback && message.messageId && (
                                        <MessageFeedbackButtons
                                            liked={message.liked}
                                            onLike={(liked) => likeChatApi(message.messageId, liked)}
                                            onDislikeComment={(comment) =>
                                                disLikeCommentApi(message.messageId, comment)
                                            }
                                        />
                                    )}
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
