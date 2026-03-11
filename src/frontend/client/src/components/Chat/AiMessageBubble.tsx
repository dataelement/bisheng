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
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/avatar";
import { TextToSpeechButton } from "~/components/Voice/TextToSpeechButton";
import { useGetBsConfig } from "~/data-provider";
import { useAuthContext } from "~/hooks";
import MessageSource from "~/pages/appChat/components/MessageSource";
import ResouceModal from "~/pages/appChat/components/ResouceModal";
import { copyText } from "~/utils";
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
    ({ message, isLatest, isStreaming, onRegenerate, siblingIdx, siblingCount, setSiblingIdx }: AiMessageBubbleProps) => {
        const isUser = message.isCreatedByUser;

        if (isUser) {
            return (
                <UserBubble
                    message={message}
                    siblingIdx={siblingIdx}
                    siblingCount={siblingCount}
                    setSiblingIdx={setSiblingIdx}
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
}: {
    message: ChatMessage;
    siblingIdx?: number;
    siblingCount?: number;
    setSiblingIdx?: (idx: number) => void;
}) {
    const { user } = useAuthContext();

    return (
        <div className="flex gap-3 px-4 py-3">
            {/* Avatar */}
            <div className="shrink-0 flex justify-center">
                <Avatar className="w-6 h-6 text-xs">
                    {user?.avatar ? <AvatarImage src={user?.avatar} alt="User" /> : <AvatarName name={user?.username} />}
                </Avatar>
            </div>
            {/* Content */}
            <div className="flex-1 min-w-0">
                <div className="rc-name select-none font-semibold text-base">{user?.username}</div>
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
                <div className="bs-mkdown mb-2 whitespace-pre-wrap break-words">
                    {message.text}
                </div>
                {/* Action buttons */}
                <div className="flex items-center gap-1 mt-1.5">
                    <CopyButton text={message.text} />
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
}: {
    message: ChatMessage;
    isLatest?: boolean;
    isStreaming?: boolean;
    onRegenerate?: () => void;
    siblingIdx?: number;
    siblingCount?: number;
    setSiblingIdx?: (idx: number) => void;
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
        <div className="flex gap-3 px-4 py-3">
            {/* Avatar */}
            <div className="shrink-0 w-6 h-6 rounded-full flex items-center justify-center">
                {bsConfig?.assistantIcon.image ? <img src={__APP_ENV__.BASE_URL + bsConfig?.assistantIcon.image} alt="" />
                    : <BotIcon size={16} className="text-black" />}
            </div>
            {/* Content */}
            <div className="flex-1 min-w-0">
                <div className="model-name select-none font-semibold text-base">{modelName}</div>

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
                    <div className="text-sm text-red-500 bg-red-50 rounded-lg p-3">
                        {regularContent || "发生错误，请重试"}
                    </div>
                ) : (
                    /* Main content — uses existing Markdown with citation support */
                    <div className="bs-mkdown message-content text-sm">
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
