import { parseFailureInfo } from '~/utils/failureInfo';
import { BotIcon } from 'lucide-react';
import { useMemo } from 'react';
import ThinkingContent from './Messages/ThinkingContent';
import { groupEventsForDisplay } from './Messages/groupEvents';
import Markdown from './Messages/Content/Markdown';
import CitationReferencesDrawer, { type CitationReferencesDesktopPayload } from './Messages/Content/CitationReferencesDrawer';
import SearchWebUrls from './Messages/Content/SearchWebUrls';
import { TaskTurnPanel } from '~/components/Linsight/Execution/TaskTurnPanel';
import type { ArtifactFile } from '~/components/Linsight/Artifacts/artifactUtils';
import { TextToSpeechButton } from '~/components/Voice/TextToSpeechButton';
import { ChatErrorCard, isTransientErrorType } from '~/components/ChatErrorCard';
import { MessageFeedbackButtons } from './MessageFeedbackButtons';
import { likeChatApi, disLikeCommentApi } from '~/api/apps';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { useLocalize } from '~/hooks';
import { useMessageSelection } from '~/hooks/useMessageSelection';
import { ExportSelectionButton, MessageCheckbox } from './MessageSelection';
import { cn } from '~/utils';
import type { ChatMessage } from '~/api/chatApi';
import { ServiceBusyNotice } from '~/components/ServiceBusyNotice';
import { AgentTimeline, CopyButton, SiblingSwitch, parseMessageText } from './messageBubbleParts';
import { localizedBusinessFailure } from '~/utils/failureInfo';
const RETRYABLE_ERROR_CODES = new Set([12046, 429, 503, 10540]);

interface AssistantBubbleProps {
    message: ChatMessage;
    isLatest?: boolean;
    isStreaming?: boolean;
    onRegenerate?: () => void;
    siblingIdx?: number;
    siblingCount?: number;
    setSiblingIdx?: (idx: number) => void;
    knowledgeChatLayout?: boolean;
    allowExport?: boolean;
    allowFeedback?: boolean;
    onOpenCitationPanel?: (payload: CitationReferencesDesktopPayload) => void;
    activeCitationMessageId?: string | null;
    onPreviewFile?: (file: ArtifactFile) => void;
}

export function AssistantBubble({
    message,
    isLatest,
    isStreaming,
    onRegenerate,
    siblingIdx,
    siblingCount,
    setSiblingIdx,
    knowledgeChatLayout,
    allowExport,
    allowFeedback = true,
    onOpenCitationPanel,
    activeCitationMessageId,
    onPreviewFile,
}: AssistantBubbleProps) {
    const localize = useLocalize();

    // Prefer the backend's own classification; fall back to the status code so
    // pre-classification backends still split busy-vs-failed correctly, and land
    // on the chat-flavoured generic copy when neither says anything.
    const resolvedErrorType = message.errorType
        || (message.errorCode !== undefined && RETRYABLE_ERROR_CODES.has(message.errorCode)
            ? "rate_limit"
            : "chat_unknown");

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
    const hasAnswerBody = !!regularContent && (finalTextIdx >= 0 || message.hasAnswerContent === true);

    // What the failure notice says. When an answer body survived, the specific
    // provider error is noise — what matters is that the answer is cut short.
    const errorNotice = hasAnswerBody
        ? localize("workstation.chat.answer_interrupted")
        : localize("workstation.chat.answer_failed");

    // A failure the backend neither classified (`error_type`) nor attached a raw
    // exception to: all we have is one human-readable line (a translated
    // api_errors code, "connection lost", …). Show that line as the card's
    // description — no per-type explanation, no hint, nothing to disclose.
    const plainFailureText = localizedBusinessFailure(message.errorCode, localize) || localize("workstation.chat.answer_failed");
    const failureInfo = message.rateLimitState === 'normal' || message.rateLimitState === 'recovering' ? undefined : parseFailureInfo(message.failureInfo);
    const isPlainFailure = !hasAnswerBody && !message.errorType && !message.errorDetail;

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
                            compactImages={knowledgeChatLayout}
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
                                : "rounded-[10px] bg-white border border-[#E5E6EB] px-3 py-2 text-sm"
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
                                compactImages={knowledgeChatLayout}
                            />
                        )}
                    </div>
                )}

                {/* Error state — replaces the body when nothing streamed in, and sits
                    below it when a partial answer did. */}
                {!showWaiting && message.error && (
                    failureInfo ? (
                        <ChatErrorCard
                            errorType={resolvedErrorType}
                            failureInfo={failureInfo}
                            onRetry={isTransientError ? onRegenerate : undefined}
                            hideHint
                        />
                    ) : isTransientError ? (
                        // Transient upstream hiccup (rate limit / busy): calm neutral
                        // notice + Retry (re-sends the last user message via regenerate),
                        // never the red error bubble.
                        <ServiceBusyNotice
                            desc={
                                hasAnswerBody
                                    ? errorNotice
                                    : localize("api_errors.12046")
                            }
                            onRetry={onRegenerate}
                        />
                    ) : hasAnswerBody ? (
                        // Cut short after a partial answer: the same one-line neutral
                        // notice as the transient case, minus Retry. The answer above
                        // is what matters; the specific reason would be noise, and
                        // the static attention mark (not the load gauge) says this
                        // one won't clear by waiting.
                        <ServiceBusyNotice desc={errorNotice} icon="attention" />
                    ) : (
                        // Terminal failure with no answer: the same classified card
                        // task mode uses (title + explanation per error_type, raw
                        // provider text behind "view details") instead of a red text
                        // block. With only a plain backend line to show, the card is
                        // just the title plus that line.
                        <ChatErrorCard
                            errorType={resolvedErrorType}
                            description={isPlainFailure ? plainFailureText : undefined}
                            // Daily chat never shows the per-type "建议…" line: the
                            // input box is right below, so "re-send" goes without saying.
                            hideHint
                        />
                    )
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
                                        className="flex size-6 items-center justify-center rounded-md transition-colors hover:bg-[#F7F7F7]"
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
