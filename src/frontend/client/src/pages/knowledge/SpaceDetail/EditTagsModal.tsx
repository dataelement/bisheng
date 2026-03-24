import { useState, KeyboardEvent, useEffect } from "react";
import { X } from "lucide-react";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
    Button,
} from "~/components/ui";
import { useToastContext } from "~/Providers";
import {
    SpaceTag,
    getSpaceTagsApi,
    addSpaceTagApi,
    updateFileTagsApi,
    batchUpdateTagsApi,
} from "~/api/knowledge";

interface EditTagsModalProps {
    isOpen: boolean;
    onClose: (confirmClose: boolean) => void;
    /** Called after tags are saved successfully so parent can refresh */
    onSaved?: () => void;
    spaceId: string;
    /** Single file edit — mutually exclusive with fileIds */
    fileId?: string | null;
    /** Batch mode: list of file IDs to append tags */
    fileIds?: string[];
    /** Tags currently assigned to the file (for single-file mode) */
    initialTagIds?: number[];
}

export function EditTagsModal({
    isOpen,
    onClose,
    onSaved,
    spaceId,
    fileId,
    fileIds,
    initialTagIds = [],
}: EditTagsModalProps) {
    const [spaceTags, setSpaceTags] = useState<SpaceTag[]>([]);
    // IDs of tags selected for this file
    const [selectedTagIds, setSelectedTagIds] = useState<Set<number>>(new Set());
    const [inputValue, setInputValue] = useState("");
    const [loading, setLoading] = useState(false);
    const { showToast } = useToastContext();

    const isBatchMode = !!(fileIds && fileIds.length > 0);

    // Fetch space tags and reset state when opened
    useEffect(() => {
        if (!isOpen || !spaceId) return;
        setInputValue("");
        setSelectedTagIds(new Set(initialTagIds));
        getSpaceTagsApi(spaceId)
            .then(setSpaceTags)
            .catch(() => {
                showToast({ message: "获取空间标签失败", status: "error" });
            });
    }, [isOpen, spaceId]);

    // Toggle a space tag selection
    const toggleTag = (tag: SpaceTag) => {
        setSelectedTagIds((prev) => {
            const next = new Set(prev);
            if (next.has(tag.id)) {
                next.delete(tag.id);
            } else {
                if (next.size >= 10) {
                    showToast({ message: "标签数超过限制", status: "error" });
                    return prev;
                }
                next.add(tag.id);
            }
            return next;
        });
    };

    // Enter key: create a new space tag, then select it
    const handleKeyDown = async (e: KeyboardEvent<HTMLInputElement>) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        const trimmed = inputValue.trim();
        if (!trimmed) return;

        if (trimmed.length > 8) {
            showToast({ message: "标签超过字符限制", status: "error" });
            return;
        }

        if (selectedTagIds.size >= 10) {
            showToast({ message: "标签数超过限制", status: "error" });
            return;
        }

        // Check if the tag already exists in the space
        const existing = spaceTags.find((t) => t.name === trimmed);
        if (existing) {
            // Just select it
            setSelectedTagIds((prev) => new Set(prev).add(existing.id));
            setInputValue("");
            return;
        }

        // Create a new tag in the space
        try {
            const newTag = await addSpaceTagApi(spaceId, trimmed);
            if (!newTag || newTag.id === undefined || newTag.id === null) {
                showToast({ message: "创建标签失败：返回数据异常", status: "error" });
                return;
            }
            setSpaceTags((prev) => [...prev, newTag]);
            setSelectedTagIds((prev) => new Set(prev).add(newTag.id));
            setInputValue("");
        } catch {
            showToast({ message: "创建标签失败", status: "error" });
        }
    };

    // Save: update file tags via API
    const handleSave = async () => {
        setLoading(true);
        try {
            const tagIds = Array.from(selectedTagIds);
            if (isBatchMode && fileIds) {
                // Batch append mode
                await batchUpdateTagsApi(spaceId, {
                    file_ids: fileIds.map(Number),
                    tag_ids: tagIds,
                });
                showToast({ message: "批量添加标签成功", status: "success" });
            } else if (fileId) {
                // Single file overwrite mode
                await updateFileTagsApi(spaceId, fileId, tagIds);
                showToast({ message: "标签保存成功", status: "success" });
            }
            onSaved?.();
            onClose(true);
        } catch {
            showToast({ message: "标签保存失败", status: "error" });
        } finally {
            setLoading(false);
        }
    };

    const handleClose = () => {
        const hasChanges = isBatchMode
            ? selectedTagIds.size > 0
            : JSON.stringify(Array.from(selectedTagIds).sort()) !==
              JSON.stringify([...initialTagIds].sort());
        onClose(!hasChanges);
    };

    // Derive selected tag names for display in input area
    const selectedTags = spaceTags.filter((t) => selectedTagIds.has(t.id));

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
            <DialogContent className="gap-0 sm:max-w-[600px] w-[600px] p-0 bg-white border-none shadow-[0px_5px_22px_0px_rgba(61,68,110,0.2)] rounded-xl outline-none flex flex-col items-stretch [&>button]:hidden">
                <DialogHeader className="px-6 py-3 h-12 border-none space-y-0 text-left shrink-0">
                    <DialogTitle className="text-[16px] font-medium text-[#212121] leading-[24px]">
                        {isBatchMode ? "批量添加标签" : "编辑标签"}
                    </DialogTitle>
                </DialogHeader>

                <div className="flex flex-col flex-1 gap-3 px-6 py-6 pb-2">
                    {/* Tags Input Box */}
                    <div
                        className="relative flex items-center flex-wrap gap-1 border border-[#ebecf0] rounded-lg px-3 py-1.5 min-h-[22px] focus-within:border-primary transition-colors bg-white pr-[40px] cursor-text"
                        onClick={() => document.getElementById("tag-input")?.focus()}
                    >
                        {selectedTags.map((tag) => (
                            <span
                                key={tag.id}
                                className="flex items-center justify-center bg-[#f2f3f5] text-[#4e5969] px-2 h-[22px] rounded-[4px] text-sm leading-[22px] whitespace-nowrap gap-1"
                            >
                                {tag.name}
                                <button
                                    className="text-[#86909c] hover:text-[#4e5969] flex items-center justify-center w-4 h-4"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        toggleTag(tag);
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
                            placeholder={
                                selectedTags.length === 0 && !inputValue
                                    ? "请输入要添加的标签，回车保存"
                                    : ""
                            }
                            className="flex-1 min-w-[120px] bg-transparent outline-none text-sm leading-[22px] text-[#212121] placeholder-[#86909c] min-h-[22px]"
                            maxLength={8}
                        />
                        <span className="text-[14px] leading-[22px] text-[#999] absolute right-3 h-full flex items-center top-0">
                            {selectedTagIds.size}/10
                        </span>
                    </div>

                    <div className="w-full h-px bg-[#ebecf0] my-[-1px]" />

                    {/* Existing Space Tags */}
                    <div className="flex flex-col gap-2 pt-1">
                        <div className="text-[12px] leading-[20px] text-[#212121]">已有标签</div>
                        <div className="flex flex-wrap gap-1">
                            {spaceTags.length === 0 && (
                                <span className="text-[12px] text-[#86909c]">暂无标签</span>
                            )}
                            {spaceTags.map((tag) => {
                                const isSelected = selectedTagIds.has(tag.id);
                                return (
                                    <span
                                        key={tag.id}
                                        onClick={() => toggleTag(tag)}
                                        className={`px-2 h-7 flex items-center justify-center text-[12px] leading-[20px] rounded-[4px] transition-colors ${
                                            isSelected
                                                ? "text-[#165dff] cursor-default bg-primary/10"
                                                : "bg-[#f2f3f5] text-[#4e5969] hover:bg-[#e5e6eb] cursor-pointer"
                                        }`}
                                    >
                                        {tag.name}
                                    </span>
                                );
                            })}
                        </div>
                    </div>
                </div>

                <DialogFooter className="flex justify-end gap-3 px-6 py-3 border-none mt-2 sm:space-x-0 h-16 items-center shrink-0">
                    <Button variant="outline" className="h-8 px-4" onClick={handleClose}>
                        取消
                    </Button>
                    <Button
                        variant="default"
                        className="h-8 px-4"
                        onClick={handleSave}
                        disabled={loading}
                    >
                        确认
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
