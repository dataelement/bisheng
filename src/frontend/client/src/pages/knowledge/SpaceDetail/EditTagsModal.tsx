import { useState, KeyboardEvent, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Trash2, X } from "lucide-react";
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
    deleteSpaceTagApi,
    updateFileTagsApi,
    batchUpdateTagsApi,
} from "~/api/knowledge";
import { useLocalize } from "~/hooks";
import { getFullWidthLength } from "~/utils";

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
    const localize = useLocalize();
    const [spaceTags, setSpaceTags] = useState<SpaceTag[]>([]);
    // IDs of tags selected for this file
    const [selectedTagIds, setSelectedTagIds] = useState<Set<number>>(new Set());
    const [inputValue, setInputValue] = useState("");
    const [loading, setLoading] = useState(false);
    const [deletingTagId, setDeletingTagId] = useState<number | null>(null);
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();

    const isBatchMode = !!(fileIds && fileIds.length > 0);

    // Fetch space tags and reset state when opened
    useEffect(() => {
        if (!isOpen || !spaceId) return;
        setInputValue("");
        setSelectedTagIds(new Set(initialTagIds));
        getSpaceTagsApi(spaceId)
            .then(setSpaceTags)
            .catch(() => {
                showToast({ message: localize("com_knowledge.fetch_tags_failed"), status: "error" });
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
                    showToast({ message: localize("com_knowledge.tags_count_limit_exceeded"), status: "error" });
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

        if (getFullWidthLength(trimmed) > 8) {
            showToast({ message: localize("com_knowledge.tags_char_limit_exceeded"), status: "error" });
            return;
        }

        if (selectedTagIds.size >= 10) {
            showToast({ message: localize("com_knowledge.tags_count_limit_exceeded"), status: "error" });
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

        if (spaceTags.length >= 50) {
            showToast({ message: localize("com_knowledge.space_tags_limit_exceeded"), status: "error" });
            return;
        }

        // Create a new tag in the space
        try {
            const newTag = await addSpaceTagApi(spaceId, trimmed);
            if (!newTag || newTag.id === undefined || newTag.id === null) {
                showToast({ message: localize("com_knowledge.create_tag_failed_abnormal"), status: "error" });
                return;
            }
            setSpaceTags((prev) => [...prev, newTag]);
            setSelectedTagIds((prev) => new Set(prev).add(newTag.id));
            setInputValue("");
            // Invalidate shared cache so search dropdown updates
            queryClient.invalidateQueries({ queryKey: ['spaceTags', spaceId] });
        } catch {
            showToast({ message: localize("com_knowledge.create_tag_failed"), status: "error" });
        }
    };

    // Save: update file tags via API
    const handleSave = async () => {
        const pendingText = inputValue.trim();

        setLoading(true);

        try {
            const tagIds = Array.from(selectedTagIds);
            if (isBatchMode && fileIds) {
                // Batch append mode
                await batchUpdateTagsApi(spaceId, {
                    file_ids: fileIds.map(Number),
                    tag_ids: tagIds,
                });
                showToast({ message: localize("com_knowledge.batch_add_tags_success"), status: "success" });
            } else if (fileId) {
                // Single file overwrite mode
                await updateFileTagsApi(spaceId, fileId, tagIds);
                !pendingText && showToast({ message: localize("com_knowledge.tag_save_success"), status: "success" });
            }
            onSaved?.();
            // Invalidate shared spaceTags cache so search dropdown picks up new tags
            queryClient.invalidateQueries({ queryKey: ['spaceTags', spaceId] });
            onClose(true);
        } catch {
            showToast({ message: localize("com_knowledge.tag_save_failed"), status: "error" });
        } finally {
            setLoading(false);
        }
    };

    const handleDeleteSpaceTag = async (tag: SpaceTag) => {
        if (deletingTagId !== null) return;
        setDeletingTagId(tag.id);
        try {
            await deleteSpaceTagApi(spaceId, tag.id);
            setSpaceTags((prev) => prev.filter((item) => item.id !== tag.id));
            setSelectedTagIds((prev) => {
                const next = new Set(prev);
                next.delete(tag.id);
                return next;
            });
            queryClient.invalidateQueries({ queryKey: ['spaceTags', spaceId] });
            showToast({ message: localize("com_knowledge.delete_tag_success"), status: "success" });
        } catch {
            showToast({ message: localize("com_knowledge.delete_tag_failed"), status: "error" });
        } finally {
            setDeletingTagId(null);
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
            <DialogContent
                onPointerDownOutside={(e) => e.preventDefault()}
                onInteractOutside={(e) => e.preventDefault()}
                className="flex w-[600px] flex-col items-stretch gap-0 rounded-xl border-none bg-white p-0 shadow-[0px_5px_22px_0px_rgba(61,68,110,0.2)] outline-none touch-mobile:inset-0 touch-mobile:left-0 touch-mobile:top-0 touch-mobile:h-dvh touch-mobile:w-screen touch-mobile:max-w-none touch-mobile:translate-x-0 touch-mobile:translate-y-0 touch-mobile:rounded-none [&>button]:hidden"
            >
                <DialogHeader className="h-auto shrink-0 space-y-0 px-6 py-4 text-left touch-mobile:px-4 touch-mobile:pt-6 touch-mobile:pb-4">
                    <DialogTitle className="text-[16px] leading-6 font-medium text-[#212121]">
                        {isBatchMode ? localize("com_knowledge.batch_add_tags") : localize("com_knowledge.edit_tags")}
                    </DialogTitle>
                    <button
                        type="button"
                        onClick={handleClose}
                        className="absolute right-4 top-4 inline-flex size-8 items-center justify-center rounded-md text-[#4E5969] transition-colors hover:bg-[#F2F3F5]"
                        aria-label={localize("com_knowledge.close") || "Close"}
                    >
                        <X className="size-4" />
                    </button>
                </DialogHeader>

                <div className="flex flex-1 flex-col gap-4 px-6 py-6 pb-2 touch-mobile:px-4 touch-mobile:py-4">
                    {/* Tags Input Box */}
                    <div
                        className="relative flex min-h-8 cursor-text flex-wrap items-center gap-1 rounded-[8px] border border-[#EBECF0] bg-white px-3 py-[5px] pr-[40px] transition-colors focus-within:border-primary"
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
                                    ? localize("com_knowledge.input_tags_placeholder")
                                    : ""
                            }
                            className="flex-1 min-w-[120px] bg-transparent outline-none text-sm leading-[22px] text-[#212121] placeholder-[#86909c] min-h-[22px]"
                        // maxLength={8}
                        />
                        <span className="absolute right-3 top-0 flex h-full items-center text-[14px] leading-[22px] text-[#999]">
                            {selectedTagIds.size}/10
                        </span>
                    </div>

                    {/* <div className="w-full h-px bg-[#ebecf0] my-[-1px]" /> */}

                    {/* Existing Space Tags */}
                    <div className="flex flex-col gap-2 pt-1">
                        <div className="text-[14px] leading-5 font-medium text-[#212121]">{localize("com_knowledge.existing_tags")}</div>
                        <div className="flex flex-wrap gap-1">
                            {spaceTags.length === 0 && (
                                <span className="text-[12px] text-[#86909c]">{localize("com_knowledge.no_tags")}</span>
                            )}
                            {spaceTags.map((tag) => {
                                const isSelected = selectedTagIds.has(tag.id);
                                return (
                                    <span
                                        key={tag.id}
                                        onClick={() => toggleTag(tag)}
                                        className={`px-2 h-7 flex items-center justify-center gap-1 text-[12px] leading-[20px] rounded-[4px] transition-colors ${isSelected
                                            ? "text-[#165dff] cursor-default bg-primary/10"
                                            : "bg-[#f2f3f5] text-[#4e5969] hover:bg-[#e5e6eb] cursor-pointer"
                                            }`}
                                    >
                                        {tag.name}
                                        <button
                                            type="button"
                                            className="flex items-center justify-center text-[#86909c] hover:text-[#f53f3f] disabled:cursor-not-allowed disabled:text-[#c9cdd4]"
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                void handleDeleteSpaceTag(tag);
                                            }}
                                            disabled={deletingTagId === tag.id}
                                            title={localize("com_knowledge.delete")}
                                        >
                                            <Trash2 className="size-3" />
                                        </button>
                                    </span>
                                );
                            })}
                        </div>
                    </div>
                </div>

                <DialogFooter className="mt-2 flex h-16 shrink-0 items-center justify-end gap-3 border-none px-6 py-3 touch-mobile:!mt-auto touch-mobile:!h-auto touch-mobile:!flex-row touch-mobile:!justify-stretch touch-mobile:border-t touch-mobile:border-[#ECECEC] touch-mobile:px-4 touch-mobile:py-3 sm:space-x-0">
                    <Button variant="outline" className="h-8 rounded-[6px] px-4 font-normal touch-mobile:flex-1" onClick={handleClose}>
                        {localize("com_knowledge.cancel")}</Button>
                    <Button
                        variant="default"
                        className="h-8 rounded-[6px] px-4 font-normal touch-mobile:flex-1"
                        onClick={handleSave}
                        disabled={loading}
                    >
                        {localize("com_knowledge.confirm")}</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
