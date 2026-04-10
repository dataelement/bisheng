/**
 * Single message bubble for user / assistant messages.
 */
import {
    BotIcon,
    CheckIcon,
    ChevronLeftIcon,
    ChevronRightIcon,
    CopyIcon,
    RefreshCwIcon
} from "lucide-react";
import { memo, useCallback, useMemo, useState, useRef } from "react";
import Thinking from "~/components/Artifacts/Thinking";
import Markdown from "~/components/Chat/Messages/Content/Markdown";
import SearchWebUrls from "~/components/Chat/Messages/Content/SearchWebUrls";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
import { TextToSpeechButton } from "~/components/Voice/TextToSpeechButton";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import { useAuthContext } from "~/hooks";
import MessageSource from "~/pages/appChat/components/MessageSource";
import ResouceModal from "~/pages/appChat/components/ResouceModal";
import { copyText, cn } from "~/utils";
import type { ChatMessage } from "~/api/chatApi";
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
}

// --- Copy button with feedback ---
function CopyButton({ text }: { text: string }) {
    const [copied, setCopied] = useState(false);
    const handleCopy = useCallback(() => {
        copyText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    }, [text]);

    return (
        <button
            type="button"
            onClick={handleCopy}
            className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
            title="复制"
        >
            {copied ? <CheckIcon size={16} /> : <CopyIcon size={16} />}
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
                                "px-3 py-2 whitespace-pre-wrap break-words rounded-[2px]",
                                knowledgeChatLayout
                                    ? "bg-[#F2F3F5] text-[#4E5969] text-[14px] leading-[22px]"
                                    : "rounded-[10px] bg-[#E6EDFC] text-[#1d2129] text-sm"
                            )}
                        >
                            {tag && (
                                <span
                                    className="mr-1 inline-flex h-5 max-w-[min(240px,90%)] items-center rounded-[2px] px-1 align-[-2px] text-xs font-medium text-[#212121] select-none"
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
}: {
    message: ChatMessage;
    isLatest?: boolean;
    isStreaming?: boolean;
    onRegenerate?: () => void;
    siblingIdx?: number;
    siblingCount?: number;
    setSiblingIdx?: (idx: number) => void;
    knowledgeChatLayout?: boolean;
}) {
    // Parse :::thinking::: and :::web::: from the raw text
    const { thinkingContent, webContent, regularContent } = useMemo(
        () => parseMessageText(message.text || ""),
        [message.text]
    );
    const { data: bsConfig } = useGetBsConfig()
    const sourceRef = useRef<any>(null);

    const modelName = message.sender || "AI";
    const showCursor = isLatest && isStreaming;

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

                {/* Thinking block - reuse existing Thinking component */}
                {thinkingContent && (
                    <Thinking>{thinkingContent}</Thinking>
                )}

                {/* Web search sources - reuse existing SearchWebUrls component */}
                {webContent.length > 0 && (
                    <SearchWebUrls webs={webContent} />
                )}

                {/* Error state */}
                {message.error ? (
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
                        <Markdown
                            content={regularContent}
                            webContent={webContent}
                            showCursor={showCursor}
                            isLatestMessage={!!isLatest}
                        />
                    </div>
                )}

                {/* Action buttons (only show when not streaming) */}
                {!isStreaming && regularContent && (
                    <div className="flex items-center gap-1 mt-1.5 text-gray-400">
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
                        <CopyButton text={regularContent} />
                        {onRegenerate && (
                            <button
                                type="button"
                                onClick={onRegenerate}
                                className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
                                title="regenerate"
                            >
                                <RefreshCwIcon size={16} />
                            </button>
                        )}
                        <TextToSpeechButton
                            messageId={message.messageId || ""}
                            text={regularContent}
                        />
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
