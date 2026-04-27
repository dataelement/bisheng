import { useLocalize, usePrefersMobileLayout } from "~/hooks";
/**
 * AI Assistant Panel — complete chat interface.
 * Supports three modes:
 *   - Workstation mode (default): uses useAiChat with full payload
 *   - Channel article mode: when articleDocId is provided, uses useChannelChat
 *   - File chat mode: when fileChat is provided, uses useFileChat
 */
import { BrushCleaningIcon, ChevronsRightIcon, X } from "lucide-react";
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
import useAiChat from "~/hooks/useAiChat";
import useChannelChat from "~/hooks/useChannelChat";
import useChatModelMemo from "~/hooks/useChatModelMemo";
import useFileChat from "~/hooks/useFileChat";
import { useConfirm } from "~/Providers";
import { ChannelClearIcon } from "~/components/icons/channels";

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
    /**
     * H5 文章详情叠层：外层已有返回与标题，内层只保留清空等工具，避免双标题栏。
     */
    compactMobileChrome?: boolean;
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
    compactMobileChrome = false,
}: AiAssistantPanelProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();

    // Determine chat mode: fileChat > channel > workstation
    const isFileChatMode = !!fileChat;
    const isChannelMode = !isFileChatMode && !!articleDocId;
    const isSimpleMode = isFileChatMode || isChannelMode;

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
            title: localize("com_subscription.prompt_tip"),
            description: localize("com_subscription.clear_chat_confirm"),
            confirmText: localize("com_subscription.confirm"),
            cancelText: localize("com_subscription.cancel"),
        });
        if (ok) clearConversation();
    };

    const showCompactMobileHeader = compactMobileChrome && isH5;

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
            {/* Header */}
            {showCompactMobileHeader ? (
                <div className="relative flex h-11 shrink-0 items-center justify-between px-2">
                    <Button
                        variant="ghost"
                        className="inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-[#EBECF0] bg-white text-[#4E5969] hover:bg-[#F7F8FA]"
                        onClick={onClose}
                        aria-label={localize("com_ui_go_back")}
                    >
                        <span className="text-[14px] leading-none font-semibold text-[#4E5969]">←</span>
                    </Button>
                    <h3 className="pointer-events-none absolute left-1/2 w-[60%] -translate-x-1/2 truncate text-center text-sm leading-6 font-medium text-gray-900">
                        {localize("com_subscription.ai_assistant")}
                    </h3>
                    <div className="flex shrink-0 items-center">
                        {clearChatControl}
                    </div>
                </div>
            ) : (
                <div className={`relative flex items-center justify-between px-3 py-[15px] shrink-0 ${noBorder ? '' : 'border-b border-gray-100'}`}>
                    {isH5 && (
                        <Button
                            variant="ghost"
                            className="inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-[#EBECF0] bg-white text-[#4E5969] hover:bg-[#F7F8FA]"
                            onClick={onClose}
                        >
                            <X className="size-4" />
                        </Button>
                    )}
                    <h3 className="pointer-events-none absolute left-1/2 w-[60%] -translate-x-1/2 truncate text-center text-sm leading-6 font-medium text-gray-900 touch-desktop:pointer-events-auto touch-desktop:static touch-desktop:w-auto touch-desktop:translate-x-0 touch-desktop:text-left">
                        {localize("com_subscription.ai_assistant")}
                    </h3>
                    <div className="ml-auto flex items-center gap-3 pr-3">
                        {clearChatControl}
                        {!isH5 && (
                            <Button
                                variant="ghost"
                                className="text-gray-400 p-0.5 group relative w-5 h-5"
                                onClick={onClose}
                            >
                                <ChevronsRightIcon className="size-4" />
                            </Button>
                        )}
                    </div>
                </div>
            )}

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
                onPresetClick={(q) => setInputText(q)}
                onRegenerate={regenerate}
            />

            {/* Input Area */}
            <div className="px-2">
                <AiChatInput
                    size="mini"
                    features={features}
                    disabled={isSimpleMode ? false : !bsConfig?.models?.length}
                    placeholder={localize("com_subscription.input_question_placeholder")}
                    isStreaming={isStreaming}
                    onScrollToBottom={() => { }}
                    modelOptions={isSimpleMode ? undefined : bsConfig?.models}
                    modelValue={isSimpleMode ? undefined : chatModel.id}
                    onModelChange={isSimpleMode ? undefined : (val) => {
                        const model = bsConfig?.models?.find((m) => m.id === val);
                        setChatModel({
                            id: Number(val),
                            name: model?.displayName || "",
                        });
                    }}
                    onSend={handleSend}
                    onStop={stopGenerating}
                    value={inputText}
                    onChange={setInputText}
                    bsConfig={isSimpleMode ? undefined : bsConfig}
                    selectedOrgKbs={isSimpleMode ? [] : selectedOrgKbs}
                    onSelectedOrgKbsChange={isSimpleMode ? undefined : setSelectedOrgKbs}
                    searchType={isSimpleMode ? undefined : searchType}
                    onSearchTypeChange={isSimpleMode ? undefined : setSearchType}
                />
            </div>
        </div>
    );
}
