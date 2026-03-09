/**
 * KnowledgeAiPanel — AI assistant panel for knowledge space.
 * Reuses useAiChat hook + AiChatMessages. Extended with:
 * - Dynamic welcome text based on context (space vs folder)
 * - Session memory per location via useKnowledgeAiSession
 * - History sidebar toggle
 * - New session action
 * - Tag filter support via KnowledgeAiInput
 */
import { HistoryIcon, PlusIcon, XIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { useRecoilState } from "recoil";
import { Button } from "~/components";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "~/components/ui/Tooltip2";
import { useGetBsConfig } from "~/data-provider";
import store from "~/store";
import AiChatMessages from "~/components/Chat/AiChatMessages";
import useAiChat from "~/hooks/useAiChat";
import { useKnowledgeAiSession } from "~/hooks/useKnowledgeAiSession";
import { KnowledgeAiInput } from "./KnowledgeAiInput";
import { ConversationHistory } from "./ConversationHistory";

interface KnowledgeAiPanelProps {
    spaceId: string;
    folderId?: string;
    locationKey: string;
    contextLabel: string; // "知识空间" | "文件夹"
    availableTags?: string[];
    onClose: () => void;
}

export function KnowledgeAiPanel({
    spaceId,
    folderId,
    locationKey,
    contextLabel,
    availableTags = [],
    onClose,
}: KnowledgeAiPanelProps) {
    // Session management
    const {
        conversationId: sessionConvoId,
        setConversationId,
        clearSession,
        history,
        addToHistory,
        loadConversation,
    } = useKnowledgeAiSession(locationKey);

    const {
        messages,
        conversationId: activeConvoId,
        title: chatTitle,
        isLoading,
        isStreaming,
        sendMessage,
        stopGenerating,
        clearConversation,
        regenerate,
    } = useAiChat(sessionConvoId);

    const { data: bsConfig } = useGetBsConfig();
    const [chatModel, setChatModel] = useRecoilState(store.chatModel);
    const [showHistory, setShowHistory] = useState(false);

    const welcomeText = contextLabel === "文件夹"
        ? "基于当前文件夹问答"
        : "基于当前知识空间问答";

    // Persist conversation ID when useAiChat creates a new one
    useEffect(() => {
        if (activeConvoId && activeConvoId !== "new" && activeConvoId !== sessionConvoId) {
            setConversationId(activeConvoId);
            addToHistory({
                id: activeConvoId,
                title: chatTitle || "新的对话",
                createdAt: new Date().toISOString(),
                updatedAt: new Date().toISOString(),
            });
        }
    }, [activeConvoId, sessionConvoId, chatTitle, setConversationId, addToHistory]);

    const handleSend = (text: string, files?: any[] | null, tags?: string[]) => {
        // Tags can be used for RAG filtering in the future
        if (tags && tags.length > 0) {
            console.log("[KnowledgeAi] Sending with tag filters:", tags);
        }
        sendMessage(text, files);
    };

    const handleNewChat = () => {
        clearConversation();
        clearSession();
    };

    const handleHistorySelect = (id: string) => {
        loadConversation(id);
        setShowHistory(false);
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
            {messages.length === 0 && sessionConvoId === "new" ? (
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
                    conversationId={activeConvoId}
                    title={chatTitle}
                    isLoading={isLoading && sessionConvoId !== "new"}
                    isStreaming={isStreaming}
                    presetQuestions={[]}
                    onPresetClick={() => { }}
                    onRegenerate={regenerate}
                />
            )}

            {/* Input Area — with # tag support */}
            <KnowledgeAiInput
                availableTags={availableTags}
                isStreaming={isStreaming}
                disabled={!bsConfig?.models?.length}
                bsConfig={bsConfig}
                chatModel={chatModel}
                onChatModelChange={(val) => {
                    const model = bsConfig?.models?.find((m: any) => m.id === val);
                    setChatModel({
                        id: Number(val),
                        name: model?.displayName || "",
                    });
                }}
                onSend={handleSend}
                onStop={stopGenerating}
                onNewChat={handleNewChat}
            />

            {/* History sidebar overlay */}
            {showHistory && (
                <ConversationHistory
                    history={history}
                    activeConversationId={activeConvoId}
                    onSelect={handleHistorySelect}
                    onClose={() => setShowHistory(false)}
                />
            )}
        </div>
    );
}
