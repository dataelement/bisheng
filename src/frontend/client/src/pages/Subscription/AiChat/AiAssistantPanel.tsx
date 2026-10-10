import { useLocalize } from "~/hooks";
/**
 * AI Assistant Panel — complete chat interface.
 * Supports three modes:
 *   - Workstation mode (default): uses useAiChat with full payload
 *   - Channel article mode: when articleDocId is provided, uses useChannelChat
 *   - File chat mode: when fileChat is provided, uses useFileChat
 */
import { ChevronsRight } from "lucide-react";
import { useCallback, useState } from "react";
import { useRecoilState } from "recoil";
import { Button } from "~/components";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "~/components/ui/Tooltip2";
import { useAuthContext } from "~/hooks/AuthContext";
import { useGetBsConfig, useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider";
import store from "~/store";
import type { AiChatInputFeatures } from "~/components/Chat/AiChatInput";
import AiChatInput from "~/components/Chat/AiChatInput";
import AiChatMessages from "~/components/Chat/AiChatMessages";
import { ArticleQAIllustration } from "~/components/illustrations";
import useAiChat from "~/hooks/useAiChat";
import useChannelChat from "~/hooks/useChannelChat";
import {
    readAdminDefaultModelId,
    useChatModelResolution,
    type ChatModelOption,
} from "~/hooks/useChatModelResolution";
import { useSurfaceModel } from "~/hooks/useSurfaceModel";
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

    // Model selection splits by mode:
    //  - dock modes (channel / file) are standalone panels: their own isolated
    //    selection, which must not leak into /c (see useSurfaceModel);
    //  - workstation mode IS a regular conversation, so it resolves per
    //    conversation exactly like ChatView and keeps writing the shared atom
    //    that useAiChat reads.
    const { data: bsConfig } = useGetBsConfig();
    const { user } = useAuthContext();
    const { data: workbenchCfg } = useGetWorkbenchModelsQuery();
    const {
        model: surfaceModel,
        selectModel: selectSurfaceModel,
        repairModel: repairSurfaceModel,
    } = useSurfaceModel({
        userId: user?.id,
        surfaceKey: isFileChatMode ? 'assistantFileAi' : 'assistantChannelAi',
        models: (bsConfig?.models || []) as ChatModelOption[],
        adminDefaultId: readAdminDefaultModelId(workbenchCfg, 'daily'),
    });

    // All three hooks always called (React hooks rules); only the active one runs
    const workstationChat = useAiChat(isSimpleMode ? "new" : conversationId);
    const channelChat = useChannelChat(isChannelMode ? articleDocId! : "", surfaceModel);
    const fileChatHook = useFileChat(
        isFileChatMode ? fileChat!.spaceId : "",
        isFileChatMode ? fileChat!.fileId : "",
        surfaceModel,
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

    // Media parsing state only exists on the workstation hook; channel/file chat
    // never upload media, so they have no such flag to read off activeChat.
    const isParsingMedia = isSimpleMode ? false : workstationChat.isParsingMedia;

    const [chatModel, setChatModel] = useRecoilState(store.chatModel);
    const [selectedOrgKbs, setSelectedOrgKbs] = useRecoilState(store.selectedOrgKbs);
    const [searchType, setSearchType] = useRecoilState(store.searchType);
    const [inputText, setInputText] = useState("");

    // Workstation mode only — a dock panel resolves through useSurfaceModel above.
    const handleModelResolved = useCallback(
        (target: ChatModelOption, deliberate: boolean) => {
            setChatModel({
                id: Number(target.id),
                name: target.displayName || target.name || "",
                manual: deliberate,
                mode: 'daily',
            });
        },
        [setChatModel],
    );
    const { persistPick: persistModelPick } = useChatModelResolution({
        userId: user?.id,
        conversationId: conversationId || 'new',
        mode: 'daily',
        models: (bsConfig?.models || []) as ChatModelOption[],
        adminDefaultId: readAdminDefaultModelId(workbenchCfg, 'daily'),
        ready: !isSimpleMode && !!bsConfig?.models?.length && !!user?.id,
        onResolved: handleModelResolved,
    });

    const handleModelChange = useCallback(
        (val: string | number) => {
            if (isSimpleMode) {
                selectSurfaceModel(val);
                return;
            }
            const picked = bsConfig?.models?.find((m: ChatModelOption) => String(m.id) === String(val));
            persistModelPick(val);
            setChatModel({
                id: Number(val),
                name: picked?.displayName || "",
                manual: true,
                mode: 'daily',
            });
        },
        [isSimpleMode, selectSurfaceModel, bsConfig, persistModelPick, setChatModel],
    );

    // AiModelSelect repairing an invalid value is not a user pick — never persisted.
    const handleModelAutoChange = useCallback(
        (val: string | number) => {
            if (isSimpleMode) {
                repairSurfaceModel(val);
                return;
            }
            const picked = bsConfig?.models?.find((m: ChatModelOption) => String(m.id) === String(val));
            setChatModel((prev) => ({
                id: Number(val),
                name: picked?.displayName || prev.name || "",
                manual: prev.manual ?? false,
                mode: prev.mode,
            }));
        },
        [isSimpleMode, repairSurfaceModel, bsConfig, setChatModel],
    );

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
                    {/* Admin-customizable assistant name per surface; empty/absent
                        falls back to the localized default. fileChat is a
                        knowledge-space surface, otherwise it's the subscription surface. */}
                    {fileChat
                        ? bsConfig?.knowledge_space?.assistant_name?.trim() ||
                          localize("com_knowledge.ai_assistant")
                        : bsConfig?.subscription?.assistant_name?.trim() ||
                          localize("com_subscription.ai_assistant")}
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
                                    className="size-8 shrink-0 text-text-3 hover:text-text-2"
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
                emptyStateIllustration={<ArticleQAIllustration grey className="mx-auto block size-[80px]" />}
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
                    isParsingMedia={isParsingMedia}
                    onScrollToBottom={() => { }}
                    modelOptions={allowModelSelect ? bsConfig?.models : undefined}
                    modelValue={allowModelSelect ? (isSimpleMode ? surfaceModel.id : chatModel.id) : undefined}
                    onModelChange={allowModelSelect ? handleModelChange : undefined}
                    onModelAutoChange={allowModelSelect ? handleModelAutoChange : undefined}
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
