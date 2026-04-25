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
import { HistoryIcon } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
import { useLocalize } from "~/hooks";
import { getSpaceTagsApi } from "~/api/knowledge";

interface KnowledgeAiPanelProps {
    spaceId: string;
    folderId?: string;
    contextLabel: string; // "知识空间" | "文件夹"
    onClose: () => void;
}

export function KnowledgeAiPanel({
    spaceId,
    folderId,
    contextLabel,
    onClose,
}: KnowledgeAiPanelProps) {
    const localize = useLocalize();

    // Fetch space tags via react-query (cache shared with other consumers)
    const { data: availableTags = [] } = useQuery({
        queryKey: ['spaceTags', spaceId],
        queryFn: () => getSpaceTagsApi(spaceId),
        enabled: !!spaceId,
    });

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
        renameSession,
        regenerate,
    } = useFolderChat(spaceId, folderId);

    const [showHistory, setShowHistory] = useState(false);

    // Empty-state hint depends on whether the panel is opened inside a folder
    // (folderId is set) or at the space root.
    const folderQaHint = folderId
        ? localize("com_knowledge.qa_current_folder")
        : localize("com_knowledge.qa_current_space");

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

    const handleRenameSession = (chatId: string, name: string) =>
        renameSession(chatId, name);

    return (
        <div className="flex flex-col h-full bg-white relative">
            {/* Header */}
            <div className="relative flex items-center justify-between px-4 py-3 shrink-0">
                <div className="w-7 h-7 shrink-0" aria-hidden />
                <h3 className="pointer-events-none absolute left-1/2 w-[60%] -translate-x-1/2 truncate text-center text-sm leading-6 font-medium text-[#1d2129]">
                    {localize("com_knowledge.ai_assistant")}
                </h3>
                <div className="ml-auto flex items-center gap-1">
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
                                <p>{localize("com_knowledge.history_chat")}</p>
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
                                    <img
                                        className="size-4"
                                        src={`${__APP_ENV__.BASE_URL}/assets/channel/message-circle.svg`}
                                        alt=""
                                    />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent>
                                <p>{localize("com_knowledge.create_chat")}</p>
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
                                    <svg
                                        className="size-4"
                                        viewBox="0 0 24 24"
                                        fill="none"
                                        xmlns="http://www.w3.org/2000/svg"
                                        aria-hidden
                                    >
                                        <path
                                            d="M15 18L9 12L15 6"
                                            stroke="#4E5969"
                                            strokeWidth="2.25"
                                            strokeLinecap="round"
                                            strokeLinejoin="round"
                                        />
                                    </svg>
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent>
                                <p>{localize("com_knowledge.close")}</p>
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </div>
            </div>

            {/* Messages Area */}
            {messages.length === 0 && !activeChatId ? (
                // Welcome screen
                <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
                    <img
                        className="mx-auto block size-[80px] object-contain"
                        src={`${__APP_ENV__.BASE_URL}/assets/channel/ai-home.png`}
                        alt="AI Assistant"
                    />
                    <p className="text-sm text-[#86909c]">{folderQaHint}</p>
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
                    hideHeaderTitle
                    flatMode
                    knowledgeChatLayout
                    emptyStateHint={folderQaHint}
                    onPresetClick={() => { }}
                    onRegenerate={regenerate}
                />
            )}

            {/* Input Area — with # tag support */}
            <KnowledgeAiInput
                key={spaceId}
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
                    onRename={handleRenameSession}
                    onClose={() => setShowHistory(false)}
                />
            )}
        </div>
    );
}
