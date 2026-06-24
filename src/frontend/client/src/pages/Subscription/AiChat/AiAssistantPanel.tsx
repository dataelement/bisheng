import { useLocalize } from "~/hooks";
/**
 * AI Assistant Panel — complete chat interface.
 * Supports three modes:
 *   - Workstation mode (default): uses useAiChat with full payload
 *   - Channel article mode: when articleDocId is provided, uses useChannelChat
 *   - File chat mode: when fileChat is provided, uses useFileChat
 */
import { ChevronsRight } from "lucide-react";
import { useState } from "react";
import { useRecoilState } from "recoil";
import { Button } from "~/components";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "~/components/ui/Tooltip2";
import { useAuthContext } from "~/hooks/AuthContext";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import store from "~/store";
import type { AiChatInputFeatures } from "~/components/Chat/AiChatInput";
import AiChatInput from "~/components/Chat/AiChatInput";
import AiChatMessages from "~/components/Chat/AiChatMessages";
import { ArticleQAIllustration } from "~/components/illustrations";
import useAiChat from "~/hooks/useAiChat";
import useChannelChat from "~/hooks/useChannelChat";
import useChatModelMemo from "~/hooks/useChatModelMemo";
import useFileChat from "~/hooks/useFileChat";
import { useConfirm } from "~/Providers";
import { ChannelClearIcon } from "~/components/icons/channels";
import { cn } from "~/utils";

interface AiAssistantPanelProps {
    onClose: () => void;
    conversationId?: string;
    features?: AiChatInputFeatures;
    /** When true, the header won't render a bottom border */
    noBorder?: boolean;
    /** ES article document ID — when provided, switches to channel chat mode */
    articleDocId?: string;
    /** Knowledge space file chat — when provided, switches to file chat mode */
    fileChat?: { spaceId: string; fileId: string };
}

/**
 * AI Assistant Panel — a complete chat interface.
 */
export function AiAssistantPanel({
    onClose,
    conversationId = "new",
    features,
    noBorder,
    articleDocId,
    fileChat,
}: AiAssistantPanelProps) {
    const localize = useLocalize();

    // Determine chat mode: fileChat > channel > workstation
    const isFileChatMode = !!fileChat;
    const isChannelMode = !isFileChatMode && !!articleDocId;
    const isSimpleMode = isFileChatMode || isChannelMode;
    // Respect the caller's `features.modelSelect` hint when provided. Defaults to the
    // historical behaviour (off in file-chat mode). FilePreviewPage now explicitly opts
    // in for the knowledge-space file Q&A surface — without this override the model
    // dropdown is silently force-hidden via `modelOptions=undefined` in AiChatInput.
    const allowModelSelect = features?.modelSelect ?? !isFileChatMode;
    const allowAdvancedSelectors = !isSimpleMode;

    // All three hooks always called (React hooks rules); only the active one runs
    const workstationChat = useAiChat(isSimpleMode ? "new" : conversationId);
    const channelChat = useChannelChat(isChannelMode ? articleDocId! : "");
    const fileChatHook = useFileChat(
        isFileChatMode ? fileChat!.spaceId : "",
        isFileChatMode ? fileChat!.fileId : ""
    );

    // Pick the active chat based on mode
    const activeChat = isFileChatMode
        ? fileChatHook
        : isChannelMode
            ? channelChat
            : workstationChat;

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
    } = activeChat;

    const { data: bsConfig } = useGetBsConfig();
    const { user } = useAuthContext();
    const [chatModel, setChatModel] = useRecoilState(store.chatModel);
    const [selectedOrgKbs, setSelectedOrgKbs] = useRecoilState(store.selectedOrgKbs);
    const [searchType, setSearchType] = useRecoilState(store.searchType);
    const [inputText, setInputText] = useState("");

    // Hydrate / persist chatModel under bs:{uid}:chatModel so model selection
    // on Subscription / Article / FilePreview pages survives refresh and gets
    // wiped on re-login alongside the rest of bs:*.
    useChatModelMemo(user, bsConfig as any);

    const confirm = useConfirm();

    const presetQuestions = [
        localize("com_subscription.summarize_article_points"),
        localize("com_subscription.main_conclusion")
    ];

    const handleSend = (text: string, files?: any[] | null) => {
        sendMessage(text, files);
        setInputText("");
    };

    const handleClearConversation = async () => {
        const ok = await confirm({
            variant: "destructive",
            title: localize("com_subscription.clear_chat_title"),
            description: localize("com_subscription.clear_chat_confirm"),
            confirmText: localize("com_subscription.clear_chat_action"),
            cancelText: localize("com_subscription.clear_chat_cancel"),
        });
        if (ok) clearConversation();
    };

    const clearChatControl = (
        <TooltipProvider>
            <Tooltip>
                <TooltipTrigger asChild>
                    <Button
                        variant="ghost"
                        className="text-gray-400 p-0.5 group relative w-5 h-5"
                        onClick={handleClearConversation}
                    >
                        <ChannelClearIcon className="size-4" />
                    </Button>
                </TooltipTrigger>
                <TooltipContent>
                    <p>{localize("com_subscription.clear_chat")}</p>
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );

    return (
        <div className="flex flex-col h-full bg-white relative">
            {/* Header：标题左、中间空、右侧清空 + 收起（与知识空间 KnowledgeAiPanel 一致） */}
            <div
                className={cn(
                    'relative flex shrink-0 items-center gap-2 px-3 py-[15px]',
                    noBorder ? '' : 'border-b border-gray-100',
                )}
            >
                <h3 className="pointer-events-none min-w-0 shrink truncate text-left text-sm font-medium leading-6 text-gray-900">
                    {localize(
                        fileChat
                            ? "com_knowledge.ai_assistant"
                            : "com_subscription.ai_assistant",
                    )}
                </h3>
                <div className="min-w-0 flex-1" aria-hidden />
                <div className="flex shrink-0 items-center gap-2">
                    {clearChatControl}
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <Button
                                    variant="ghost"
                                    type="button"
                                    size="icon"
                                    className="size-8 shrink-0 text-[#86909c] hover:text-[#4e5969]"
                                    onClick={onClose}
                                    aria-label={localize("com_ui_collapse")}
                                >
                                    <ChevronsRight className="size-4 shrink-0" strokeWidth={2} aria-hidden />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent side="bottom">
                                <p>{localize("com_ui_collapse")}</p>
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </div>
            </div>

            {/* Messages Area */}
            <AiChatMessages
                messages={messages}
                conversationId={activeConvoId}
                title={chatTitle}
                isLoading={isSimpleMode ? isLoading : (isLoading && conversationId !== "new")}
                isStreaming={isStreaming}
                presetQuestions={presetQuestions}
                hideShare={isSimpleMode}
                hideHeaderTitle
                flatMode={isSimpleMode}
                knowledgeChatLayout
                contentWidthClassName="max-w-none px-4"
                emptyStateIllustration={<ArticleQAIllustration className="mx-auto block size-[80px]" />}
                onPresetClick={(q) => setInputText(q)}
                onRegenerate={regenerate}
            />

            {/* Input Area */}
            <div className="px-2">
                <AiChatInput
                    size="mini"
                    features={features}
                    disabled={allowModelSelect ? !bsConfig?.models?.length : false}
                    placeholder={localize("com_subscription.input_question_placeholder")}
                    isStreaming={isStreaming}
                    onScrollToBottom={() => { }}
                    modelOptions={allowModelSelect ? bsConfig?.models : undefined}
                    modelValue={allowModelSelect ? chatModel.id : undefined}
                    onModelChange={allowModelSelect ? (val) => {
                        const model = bsConfig?.models?.find((m) => m.id === val);
                        setChatModel({
                            id: Number(val),
                            name: model?.displayName || "",
                        });
                    } : undefined}
                    onSend={handleSend}
                    onStop={stopGenerating}
                    value={inputText}
                    onChange={setInputText}
                    bsConfig={allowAdvancedSelectors ? bsConfig : undefined}
                    selectedOrgKbs={allowAdvancedSelectors ? selectedOrgKbs : []}
                    onSelectedOrgKbsChange={allowAdvancedSelectors ? setSelectedOrgKbs : undefined}
                    searchType={allowAdvancedSelectors ? searchType : undefined}
                    onSearchTypeChange={allowAdvancedSelectors ? setSearchType : undefined}
                />
            </div>
        </div>
    );
}
