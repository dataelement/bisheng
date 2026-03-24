import { useLocalize } from "~/hooks";
/**
 * AI Assistant Panel — complete chat interface.
 * Supports two modes:
 *   - Workstation mode (default): uses useAiChat with full payload
 *   - Channel article mode: when articleDocId is provided, uses useChannelChat with simplified payload
 */
import { BrushCleaningIcon, ChevronsRightIcon } from "lucide-react";
import { useState } from "react";
import { useRecoilState } from "recoil";
import { Button } from "~/components";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "~/components/ui/Tooltip2";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import store from "~/store";
import type { AiChatInputFeatures } from "~/components/Chat/AiChatInput";
import AiChatInput from "~/components/Chat/AiChatInput";
import AiChatMessages from "~/components/Chat/AiChatMessages";
import useAiChat from "~/hooks/useAiChat";
import useChannelChat from "~/hooks/useChannelChat";
import { useConfirm } from "~/Providers";

interface AiAssistantPanelProps {
    onClose: () => void;
    conversationId?: string;
    features?: AiChatInputFeatures;
    /** When true, the header won't render a bottom border */
    noBorder?: boolean;
    /** ES article document ID — when provided, switches to channel chat mode */
    articleDocId?: string;
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
}: AiAssistantPanelProps) {
    const localize = useLocalize();

    // Determine chat mode based on articleDocId
    const isChannelMode = !!articleDocId;

    // Both hooks are always called (React hooks rules), but only one is active
    const workstationChat = useAiChat(isChannelMode ? "new" : conversationId);
    const channelChat = useChannelChat(isChannelMode ? articleDocId : "");

    // Pick the active chat based on mode
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
    } = isChannelMode ? channelChat : workstationChat;

    const { data: bsConfig } = useGetBsConfig();
    const [chatModel, setChatModel] = useRecoilState(store.chatModel);
    const [selectedOrgKbs, setSelectedOrgKbs] = useRecoilState(store.selectedOrgKbs);
    const [searchType, setSearchType] = useRecoilState(store.searchType);
    const [inputText, setInputText] = useState("");

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

    return (
        <div className="flex flex-col h-full bg-white relative">
            {/* Header */}
            <div className={`flex items-center justify-between px-3 py-[15px] shrink-0 ${noBorder ? '' : 'border-b border-gray-100'}`}>
                <h3 className="text-sm leading-6 font-medium text-gray-900">{localize("com_subscription.ai_assistant")}</h3>
                <div className="flex items-center gap-3 pr-3">
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <Button
                                    variant="ghost"
                                    className="text-gray-400 p-0.5 group relative w-5 h-5"
                                    onClick={handleClearConversation}
                                >
                                    <BrushCleaningIcon className="size-full" />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent>
                                <p>{localize("com_subscription.clear_chat")}</p>
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                    <Button
                        variant="ghost"
                        className="text-gray-400 p-0.5 group relative w-5 h-5"
                        onClick={onClose}
                    >
                        <ChevronsRightIcon className="size-full" />
                    </Button>
                </div>
            </div>

            {/* Messages Area */}
            <AiChatMessages
                messages={messages}
                conversationId={activeConvoId}
                title={chatTitle}
                isLoading={isChannelMode ? isLoading : (isLoading && conversationId !== "new")}
                isStreaming={isStreaming}
                presetQuestions={presetQuestions}
                hideShare={isChannelMode}
                onPresetClick={(q) => setInputText(q)}
                onRegenerate={regenerate}
            />

            {/* Input Area */}
            <AiChatInput
                size="mini"
                features={features}
                disabled={isChannelMode ? false : !bsConfig?.models?.length}
                placeholder={localize("com_subscription.input_question_placeholder")}
                isStreaming={isStreaming}
                modelOptions={isChannelMode ? undefined : bsConfig?.models}
                modelValue={isChannelMode ? undefined : chatModel.id}
                onModelChange={isChannelMode ? undefined : (val) => {
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
                bsConfig={isChannelMode ? undefined : bsConfig}
                selectedOrgKbs={isChannelMode ? [] : selectedOrgKbs}
                onSelectedOrgKbsChange={isChannelMode ? undefined : setSelectedOrgKbs}
                searchType={isChannelMode ? undefined : searchType}
                onSearchTypeChange={isChannelMode ? undefined : setSearchType}
            />
        </div>
    );
}

