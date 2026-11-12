/** Single message bubble public entry and user attachment rendering. */
import { memo, useMemo } from 'react';
import type { CitationReferencesDesktopPayload } from './Messages/Content/CitationReferencesDrawer';
import type { ArtifactFile } from '~/components/Linsight/Artifacts/artifactUtils';
import { Avatar, AvatarImage, AvatarName } from '~/components/ui/Avatar';
import { useAuthContext } from '~/hooks';
import { useMessageSelection } from '~/hooks/useMessageSelection';
import { MessageCheckbox } from './MessageSelection';
import { cn } from '~/utils';
import type { ChatMessage } from '~/api/chatApi';
import { MediaAttachmentChip, isMediaChipFile } from './attachments/MediaAttachmentChip';
import { ChatHistoryFileRow } from './attachments/ChatHistoryFileRow';
import { isImageFileName } from '~/components/ui/icon/File/FileIcon';
import { MessageImage } from './Messages/Content/MessageImage';
import { AssistantBubble } from './AssistantBubble';
import { CopyButton, SiblingSwitch } from './messageBubbleParts';

/**
 * Uploaded-file list for a user message. Every attachment — pictures, media,
 * documents — is a square tile in one wrapping grid, right-aligned under the
 * bubble. No horizontal scroll and no cap of its own: the row wraps at the
 * bubble's width, exactly as the picture row always did.
 */
function UploadedFileList({ files, conversationId }: { files: any[]; conversationId?: string }) {
    if (!files || files.length === 0) return null;

    return (
        <div className="mb-2 mt-1 flex flex-wrap justify-end gap-2">
            {files.map((file, i) => {
                const name = file.name || file.file_name;
                // Pictures keep their own component: the link stored on the message
                // expires, so it is re-issued at render time — a plain <img> on the
                // stored URL is what used to show "图片已失效".
                if (isImageFileName(name)) {
                    return (
                        <MessageImage
                            key={file.file_id ?? `image-${i}`}
                            conversationId={conversationId}
                            fileId={file.file_id}
                            altText={name}
                            initialUrl={file.filepath || file.file_path || file.file_url}
                        />
                    );
                }
                if (isMediaChipFile(file)) {
                    return <MediaAttachmentChip key={`media-${i}`} file={file} variant="message" />;
                }
                return <ChatHistoryFileRow key={`file-${i}`} file={file} />;
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
    taskRetryModelId?: string | number;
    onTaskModelChange?: (modelId: string, modelName: string) => void;
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
        allowExport,
        allowFeedback = true,
        onOpenCitationPanel,
        activeCitationMessageId,
        onPreviewFile,
        taskRetryModelId,
        onTaskModelChange,
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
                allowExport={allowExport}
                allowFeedback={allowFeedback}
                onOpenCitationPanel={onOpenCitationPanel}
                activeCitationMessageId={activeCitationMessageId}
                onPreviewFile={onPreviewFile}
                taskRetryModelId={taskRetryModelId}
                onTaskModelChange={onTaskModelChange}
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
                {/* Uploaded files: square tiles wrapping under the bubble. */}
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

export default AiMessageBubble;
