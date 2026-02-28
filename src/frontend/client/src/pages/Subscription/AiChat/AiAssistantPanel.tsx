import { ArrowUp, BrushCleaningIcon, ChevronsRightIcon, CornerDownRightIcon, Mic, Square } from "lucide-react";
import { useState } from "react";
import { Button } from "~/components";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "~/components/ui/Tooltip2";
import { useConfirm } from "~/Providers";

interface AiAssistantPanelProps {
    onClose: () => void;
}

export function AiAssistantPanel({ onClose }: AiAssistantPanelProps) {
    const [inputValue, setInputValue] = useState("");
    const [isGenerating, setIsGenerating] = useState(false); // Mock generating state
    const confirm = useConfirm();

    const presetQuestions = [
        "总结文章要点",
        "文章的主要结论是什么",
        "介绍文章作者"
    ];

    const handleClear = async () => {
        const isConfirmed = await confirm({
            description: "是否要清除当前会话？"
        });
        if (isConfirmed) {
            // TODO: clear chat history when implemented
        }
    };

    return (
        <div className="flex flex-col h-full bg-white relative">
            {/* Header */}
            <div className="flex items-center justify-between px-3 py-[15px] border-b border-gray-100 shrink-0">
                <h3 className="text-sm leading-6 font-medium text-gray-900">AI 助手</h3>
                <div className="flex items-center gap-3 pr-3">
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <Button
                                    variant="ghost"
                                    className="text-gray-400 p-0.5 group relative w-5 h-5"
                                    onClick={handleClear}
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

            {/* Chat Area - Empty State */}
            <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col items-center justify-center">
                <div className="mb-6">
                    <img
                        className="size-[80px]  object-contain mx-auto block"
                        src={`${__APP_ENV__.BASE_URL}/assets/channel/ai-home.png`}
                        alt="empty"
                    />
                    <p className="text-sm mt-[22px] text-gray-800 text-center font-medium">AI 助手可以基于该文章内容进行问答</p>
                    <div className="w-full flex flex-col gap-3 pt-[22px]">
                        {presetQuestions.map((q, i) => (
                            <Button
                                key={i}
                                variant="ghost"
                                className=" bg-gray-50 active:bg-[#E6EDFC] text-sm text-gray-800 px-3 py-1 rounded-lg text-left flex items-center gap-1 group w-fit"
                                onClick={() => setInputValue(q)}
                            >
                                <div className="size-4 flex items-center justify-center">
                                    <span className="w-1.5 h-1.5 rounded-full bg-primary group-active:hidden" />
                                    <CornerDownRightIcon className="size-4 text-primary hidden group-active:block" />
                                </div>
                                {q}
                            </Button>
                        ))}
                    </div>
                </div>
            </div>

            {/* Input Area */}
            <div className="p-4 shrink-0">
                <div className="relative bg-gray-50 rounded-3xl p-3">
                    <textarea
                        className="block w-full bg-transparent border-none resize-none outline-none text-sm text-gray-800 placeholder:text-gray-400 max-h-[182x]"
                        placeholder="请输入你的问题..."
                        rows={1}
                        value={inputValue}
                        onChange={(e) => setInputValue(e.target.value)}
                    />
                    <div className="flex items-center justify-end gap-2 shrink-0">
                        <Button className="w-8 h-8 rounded-full p-0">
                            <Mic className="w-4 h-4" />
                        </Button>
                        {isGenerating ? (
                            <Button
                                className="w-8 h-8 rounded-full p-0 bg-primary/10 text-primary hover:bg-primary/20"
                                onClick={() => setIsGenerating(false)}
                            >
                                <Square className="w-3.5 h-3.5 fill-current" />
                            </Button>
                        ) : (
                            <Button
                                className={`w-8 h-8 rounded-full p-0 ${inputValue.trim() ? "" : "bg-primary/30 cursor-not-allowed"}`}
                                disabled={!inputValue.trim()}
                                onClick={() => {
                                    if (inputValue.trim()) {
                                        setIsGenerating(true);
                                        setInputValue("");
                                    }
                                }}
                            >
                                <ArrowUp className="w-4 h-4" />
                            </Button>
                        )}
                    </div>
                </div>
            </div>

        </div >
    );
}
