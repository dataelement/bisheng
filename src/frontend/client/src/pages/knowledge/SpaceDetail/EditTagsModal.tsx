import React, { useState, KeyboardEvent, useEffect } from "react";
import { X } from "lucide-react";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
    Button,
    Input
} from "~/components/ui";
import { useToastContext } from "~/Providers";

interface EditTagsModalProps {
    isOpen: boolean;
    onClose: (confirmClose: boolean) => void;
    onSave: (tags: string[]) => void;
    initialTags?: string[];
    // Represents all existing tags in this space that can be recommended
    spaceTags?: string[];
}

export function EditTagsModal({
    isOpen,
    onClose,
    onSave,
    initialTags = [],
    spaceTags = []
}: EditTagsModalProps) {
    const [currentTags, setCurrentTags] = useState<string[]>([]);
    const [inputValue, setInputValue] = useState("");
    const { showToast } = useToastContext();

    // Reset state when opened
    useEffect(() => {
        if (isOpen) {
            setCurrentTags([...initialTags]);
            setInputValue("");
        }
    }, [isOpen, initialTags]);

    const handleAddTag = (tagText: string) => {
        const trimmed = tagText.trim();
        if (!trimmed) return;

        if (trimmed.length > 8) {
            showToast({ message: "标签超过字符限制", status: "error" });
            return;
        }

        if (currentTags.length >= 10) {
            showToast({ message: "标签数超过限制", status: "error" });
            return;
        }

        if (currentTags.includes(trimmed)) {
            // Already added
            setInputValue("");
            return;
        }

        setCurrentTags([...currentTags, trimmed]);
        setInputValue("");
    };

    const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
            e.preventDefault();
            handleAddTag(inputValue);
        }
    };

    const handleRemoveTag = (tagToRemove: string) => {
        setCurrentTags(currentTags.filter((t) => t !== tagToRemove));
    };

    const handleSave = () => {
        onSave(currentTags);
    };

    const handleClose = () => {
        const hasChanges = JSON.stringify(currentTags) !== JSON.stringify(initialTags);
        if (hasChanges) {
            // Request confirm logic outside or handle here
            onClose(false); // pass false meaning user initiated close, let parent confirm if needed
        } else {
            onClose(true); // pass true meaning safe to close directly
        }
    };

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
            <DialogContent className="gap-0 sm:max-w-[600px] w-[600px] p-0 bg-white border-none shadow-[0px_5px_22px_0px_rgba(61,68,110,0.2)] rounded-xl outline-none flex flex-col items-stretch [&>button]:hidden">
                <DialogHeader className="px-6 py-3 h-12 border-none space-y-0 text-left shrink-0">
                    <DialogTitle className="text-[16px] font-medium text-[#212121] leading-[24px]">编辑标签</DialogTitle>
                </DialogHeader>

                <div className="flex flex-col flex-1 gap-3 px-6 py-6 pb-2">
                    {/* Tags Input Box */}
                    <div
                        className="relative flex items-center flex-wrap gap-1 border border-[#ebecf0] rounded-lg px-3 py-1.5 min-h-[22px] focus-within:border-primary transition-colors bg-white pr-[40px] cursor-text"
                        onClick={() => document.getElementById("tag-input")?.focus()}
                    >
                        {currentTags.map((tag) => (
                            <span
                                key={tag}
                                className="flex items-center justify-center bg-[#f2f3f5] text-[#4e5969] px-2 h-[22px] rounded-[4px] text-sm leading-[22px] whitespace-nowrap gap-1"
                            >
                                {tag}
                                <button
                                    className="text-[#86909c] hover:text-[#4e5969] flex items-center justify-center w-4 h-4"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        handleRemoveTag(tag);
                                    }}
                                >
                                    <X className="w-3.5 h-3.5" />
                                </button>
                            </span>
                        ))}
                        <input
                            id="tag-input"
                            type="text"
                            value={inputValue}
                            onChange={(e) => setInputValue(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder={currentTags.length === 0 && !inputValue ? "请输入要添加的标签，回车保存" : ""}
                            className="flex-1 min-w-[120px] bg-transparent outline-none text-sm leading-[22px] text-[#212121] placeholder-[#86909c] min-h-[22px]"
                            maxLength={8}
                        />
                        <span className="text-[14px] leading-[22px] text-[#999] absolute right-3 h-full flex items-center top-0">
                            {currentTags.length}/10
                        </span>
                    </div>

                    <div className="w-full h-px bg-[#ebecf0] my-[-1px]" /> {/* Divider */}

                    {/* Existing Tags Recommended */}
                    <div className="flex flex-col gap-2 pt-1">
                        <div className="text-[12px] leading-[20px] text-[#212121]">已有标签</div>
                        <div className="flex flex-wrap gap-1">
                            {spaceTags.map((tag) => {
                                const isAdded = currentTags.includes(tag);
                                return (
                                    <span
                                        key={tag}
                                        onClick={() => !isAdded && handleAddTag(tag)}
                                        className={`px-2 h-7 flex items-center justify-center text-[12px] leading-[20px] rounded-[4px] transition-colors ${isAdded
                                            ? " text-[#165dff] cursor-default bg-primary/10"
                                            : "bg-[#f2f3f5] text-[#4e5969] hover:bg-[#e5e6eb] cursor-pointer"
                                            }`}
                                    >
                                        {tag}
                                    </span>
                                )
                            })}
                        </div>
                    </div>
                </div>

                <DialogFooter className="flex justify-end gap-3 px-6 py-3 border-none mt-2 sm:space-x-0 h-16 items-center shrink-0">
                    <Button variant="outline" className="h-8 px-4" onClick={handleClose}>
                        取消
                    </Button>
                    <Button variant="default" className="h-8 px-4" onClick={handleSave}>
                        确认
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
