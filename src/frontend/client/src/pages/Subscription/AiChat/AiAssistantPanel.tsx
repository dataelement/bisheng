import { ApiRequestFailure } from "~/components/ApiRequestFailure";
import { Tooltip as SharedTooltip, TooltipProvider as SharedTooltipProvider } from '@bisheng/ui';
import { useLocalize } from "~/hooks";
/**
 * AI Assistant Panel — channel article chat (useChannelChat) for the
 * subscription article views.
 */
import { ChevronsRight } from "lucide-react";
import { useState } from "react";
import { Button } from "~/components";

import { useAuthContext } from "~/hooks/AuthContext";
import { useGetBsConfig, useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider";
import type { AiChatInputFeatures } from "~/components/Chat/AiChatInput";
import AiChatInput from "~/components/Chat/AiChatInput";
import AiChatMessages from "~/components/Chat/AiChatMessages";
import { ArticleQAIllustration } from "~/components/illustrations";
import useChannelChat from "~/hooks/useChannelChat";
import { readAdminDefaultModelId, type ChatModelOption } from "~/hooks/useChatModelResolution";
import { useSurfaceModel } from "~/hooks/useSurfaceModel";
import { useConfirm } from "~/Providers";
import { ChannelClearIcon } from "~/components/icons/channels";
import { cn } from "~/utils";

interface AiAssistantPanelProps {
    onClose: () => void;
    features?: AiChatInputFeatures;
    /** When true, the header won't render a bottom border */
    noBorder?: boolean;
    /** ES article document ID of the article being discussed */
    articleDocId: string;
}

/**
 * AI Assistant Panel — a complete chat interface about one article.
 */
export function AiAssistantPanel({
    onClose,
    features,
    noBorder,
    articleDocId,
}: AiAssistantPanelProps) {
    const localize = useLocalize();

    const allowModelSelect = features?.modelSelect ?? true;

    // A standalone panel: its own isolated model selection, which must not
    // leak into /c (see useSurfaceModel).
    const { data: bsConfig } = useGetBsConfig();
    const { user } = useAuthContext();
    const { data: workbenchCfg } = useGetWorkbenchModelsQuery();
    const {
        model: surfaceModel,
        selectModel: selectSurfaceModel,
        repairModel: repairSurfaceModel,
    } = useSurfaceModel({
        userId: user?.id,
        surfaceKey: 'assistantChannelAi',
        models: (bsConfig?.models || []) as ChatModelOption[],
        adminDefaultId: readAdminDefaultModelId(workbenchCfg, 'daily'),
    });

    const {
        messages,
        conversationId: activeConvoId,
        title: chatTitle,
        isLoading,
        historyError,
        isClearing,
        retryHistory,
        isStreaming,
        sendMessage,
        stopGenerating,
        clearConversation,
        regenerate,
    } = useChannelChat(articleDocId, surfaceModel);

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
            variant: "destructive",
            title: localize("com_subscription.clear_chat_title"),
            description: localize("com_subscription.clear_chat_confirm"),
            confirmText: localize("com_subscription.clear_chat_action"),
            cancelText: localize("com_subscription.clear_chat_cancel"),
        });
        if (ok) clearConversation();
    };

    const clearChatControl = (
        <SharedTooltipProvider ><SharedTooltip  content={<><p>{localize("com_subscription.clear_chat")}</p></>} ><Button
                        variant="ghost"
                        className="text-gray-400 p-0.5 group relative w-5 h-5"
                        onClick={handleClearConversation}
                    >
                        <ChannelClearIcon className="size-4" />
                    </Button></SharedTooltip></SharedTooltipProvider>
    );

    return (
        <div className="flex flex-col h-full bg-white relative">
            {/* Header: title on the left, clear + collapse on the right (same as KnowledgeAiPanel) */}
            <div
                className={cn(
                    'relative flex shrink-0 items-center gap-2 px-3 py-[15px]',
                    noBorder ? '' : 'border-b border-gray-100',
                )}
            >
                <h3 className="pointer-events-none min-w-0 shrink truncate text-left text-sm font-medium leading-6 text-gray-900">
                    {/* Admin-customizable assistant name; empty/absent falls
                        back to the localized default. */}
                    {bsConfig?.subscription?.assistant_name?.trim() ||
                        localize("com_subscription.ai_assistant")}
                </h3>
                <div className="min-w-0 flex-1" aria-hidden />
                <div className="flex shrink-0 items-center gap-2">
                    {clearChatControl}
                    <SharedTooltipProvider ><SharedTooltip  content={<><p>{localize("com_ui_collapse")}</p></>} side="bottom" ><Button
                                    variant="ghost"
                                    type="button"
                                    size="icon"
                                    className="size-8 shrink-0 text-text-3 hover:text-text-2"
                                    onClick={onClose}
                                    aria-label={localize("com_ui_collapse")}
                                >
                                    <ChevronsRight className="size-4 shrink-0" strokeWidth={2} aria-hidden />
                                </Button></SharedTooltip></SharedTooltipProvider>
                </div>
            </div>

            {/* Messages Area */}
            {historyError ? <ApiRequestFailure error={historyError} onRetry={retryHistory} /> : (<AiChatMessages
                messages={messages}
                conversationId={activeConvoId}
                title={chatTitle}
                isLoading={isLoading}
                isStreaming={isStreaming}
                presetQuestions={presetQuestions}
                hideShare
                hideHeaderTitle
                flatMode
                knowledgeChatLayout
                contentWidthClassName="max-w-none px-4"
                emptyStateIllustration={<ArticleQAIllustration grey className="mx-auto block size-[80px]" />}
                onPresetClick={(q) => setInputText(q)}
                onRegenerate={regenerate}
            />)}

            {/* Input Area */}
            <div className="px-2">
                <AiChatInput
                    size="mini"
                    features={features}
                    disabled={Boolean(historyError) || isLoading || isClearing || (allowModelSelect ? !bsConfig?.models?.length : false)}
                    placeholder={localize("com_subscription.input_question_placeholder")}
                    isStreaming={isStreaming}
                    onScrollToBottom={() => { }}
                    modelOptions={allowModelSelect ? bsConfig?.models : undefined}
                    modelValue={allowModelSelect ? surfaceModel.id : undefined}
                    onModelChange={allowModelSelect ? selectSurfaceModel : undefined}
                    onModelAutoChange={allowModelSelect ? repairSurfaceModel : undefined}
                    onSend={handleSend}
                    onStop={stopGenerating}
                    value={inputText}
                    onChange={setInputText}
                />
            </div>
        </div>
    );
}
