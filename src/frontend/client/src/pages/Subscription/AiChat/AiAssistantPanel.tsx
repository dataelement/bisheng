/**
 * AI Assistant Panel — complete chat interface.
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
import { useGetBsConfig } from "~/data-provider";
import store from "~/store";
import type { AiChatInputFeatures } from "~/components/Chat/AiChatInput";
import AiChatInput from "~/components/Chat/AiChatInput";
import AiChatMessages from "~/components/Chat/AiChatMessages";
import useAiChat from "~/hooks/useAiChat";

interface AiAssistantPanelProps {
    onClose: () => void;
    conversationId?: string;
    features?: AiChatInputFeatures;
    /** When true, the header won't render a bottom border */
    noBorder?: boolean;
}

/**
 * AI Assistant Panel — a complete chat interface.
 */
export function AiAssistantPanel({
    onClose,
    conversationId = "new",
    features,
    noBorder,
}: AiAssistantPanelProps) {
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
    } = useAiChat(conversationId);

    const { data: bsConfig } = useGetBsConfig();
    const [chatModel, setChatModel] = useRecoilState(store.chatModel);
    const [selectedOrgKbs, setSelectedOrgKbs] = useRecoilState(store.selectedOrgKbs);
    const [searchType, setSearchType] = useRecoilState(store.searchType);
    const [inputText, setInputText] = useState("");

    const presetQuestions = [
        "总结文章要点",
        "文章的主要结论是什么",
        "介绍文章作者",
    ];

    const handleSend = (text: string, files?: any[] | null) => {
        sendMessage(text, files);
        setInputText("");
    };

    return (
        <div className="flex flex-col h-full bg-white relative">
            {/* Header */}
            <div className={`flex items-center justify-between px-3 py-[15px] shrink-0 ${noBorder ? '' : 'border-b border-gray-100'}`}>
                <h3 className="text-sm leading-6 font-medium text-gray-900">
                    AI 助手
                </h3>
                <div className="flex items-center gap-3 pr-3">
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <Button
                                    variant="ghost"
                                    className="text-gray-400 p-0.5 group relative w-5 h-5"
                                    onClick={clearConversation}
                                >
                                    <BrushCleaningIcon className="size-full" />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent>
                                <p>清空对话</p>
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
                isLoading={isLoading && conversationId !== "new"}
                isStreaming={isStreaming}
                presetQuestions={presetQuestions}
                onPresetClick={(q) => setInputText(q)}
                onRegenerate={regenerate}
            />

            {/* Input Area */}
            <AiChatInput
                size="mini"
                features={features}
                disabled={!bsConfig?.models?.length}
                placeholder='请输入你的问题...'
                isStreaming={isStreaming}
                modelOptions={bsConfig?.models}
                modelValue={chatModel.id}
                onModelChange={(val) => {
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
                bsConfig={bsConfig}
                selectedOrgKbs={selectedOrgKbs}
                onSelectedOrgKbsChange={setSelectedOrgKbs}
                searchType={searchType}
                onSearchTypeChange={setSearchType}
            />
        </div>
    );
}
