/**
 * KnowledgeAiPanel — AI assistant panel for knowledge space.
 * Uses useFolderChat for server-backed session management.
 *
 * Features:
 * - Dynamic welcome text based on context (space vs folder)
 * - Server-backed session list with create/switch/delete
 * - History sidebar toggle
 * - Tag filter support via KnowledgeAiInput
 */
import { HistoryIcon, PlusIcon, XIcon } from "lucide-react";
import { useState } from "react";
import { Button } from "~/components";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "~/components/ui/Tooltip2";
import AiChatMessages from "~/components/Chat/AiChatMessages";
import useFolderChat from "~/hooks/useFolderChat";
import type { FolderChatTag } from "~/hooks/useFolderChat";
import { KnowledgeAiInput } from "./KnowledgeAiInput";
import { ConversationHistory } from "./ConversationHistory";

interface KnowledgeAiPanelProps {
    spaceId: string;
    folderId?: string;
    contextLabel: string; // "知识空间" | "文件夹"
    availableTags?: { id: number; name: string }[];
    onClose: () => void;
}

export function KnowledgeAiPanel({
    spaceId,
    folderId,
    contextLabel,
    availableTags = [],
    onClose,
}: KnowledgeAiPanelProps) {
    const {
        messages,
        sessions,
        activeChatId,
        isLoading,
        isStreaming,
        sendMessage,
        stopGenerating,
        createSession,
        switchSession,
        deleteSession,
        regenerate,
    } = useFolderChat(spaceId, folderId);

    const [showHistory, setShowHistory] = useState(false);

    const welcomeText = contextLabel === "文件夹"
        ? "基于当前文件夹问答"
        : "基于当前知识空间问答";

    const handleSend = (
        text: string,
        files?: any[] | null,
        tag?: FolderChatTag
    ) => {
        sendMessage(text, files, tag);
    };

    const handleNewChat = async () => {
        await createSession();
    };

    const handleHistorySelect = (chatId: string) => {
        switchSession(chatId);
        setShowHistory(false);
    };

    const handleDeleteSession = (chatId: string) => {
        deleteSession(chatId);
    };

    return (
        <div className="flex flex-col h-full bg-white relative">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-[#e5e6eb] shrink-0">
                <h3 className="text-sm leading-6 font-medium text-[#1d2129]">
                    AI 助手
                </h3>
                <div className="flex items-center gap-1">
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    className={`w-7 h-7 ${showHistory ? 'text-[#165dff] bg-[#e8f3ff]' : 'text-[#86909c] hover:text-[#4e5969]'}`}
                                    onClick={() => setShowHistory(!showHistory)}
                                >
                                    <HistoryIcon className="size-4" />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent>
                                <p>历史会话</p>
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>

                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    className="w-7 h-7 text-[#86909c] hover:text-[#4e5969]"
                                    onClick={handleNewChat}
                                >
                                    <PlusIcon className="size-4" />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent>
                                <p>新建会话</p>
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>

                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    className="w-7 h-7 text-[#86909c] hover:text-[#4e5969]"
                                    onClick={onClose}
                                >
                                    <XIcon className="size-4" />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent>
                                <p>关闭</p>
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </div>
            </div>

            {/* Messages Area */}
            {messages.length === 0 && !activeChatId ? (
                // Welcome screen
                <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center px-6">
                    <img
                        className="size-24 object-contain opacity-80"
                        src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                        alt="AI Assistant"
                    />
                    <p className="text-sm text-[#86909c]">{welcomeText}</p>
                </div>
            ) : (
                <AiChatMessages
                    messages={messages}
                    conversationId={activeChatId}
                    title=""
                    isLoading={isLoading}
                    isStreaming={isStreaming}
                    presetQuestions={[]}
                    hideShare
                    flatMode
                    onPresetClick={() => { }}
                    onRegenerate={regenerate}
                />
            )}

            {/* Input Area — with # tag support */}
            <KnowledgeAiInput
                availableTags={availableTags}
                isStreaming={isStreaming}
                onSend={handleSend}
                onStop={stopGenerating}
            />

            {/* History sidebar overlay */}
            {showHistory && (
                <ConversationHistory
                    sessions={sessions}
                    activeChatId={activeChatId}
                    onSelect={handleHistorySelect}
                    onDelete={handleDeleteSession}
                    onClose={() => setShowHistory(false)}
                />
            )}
        </div>
    );
}
