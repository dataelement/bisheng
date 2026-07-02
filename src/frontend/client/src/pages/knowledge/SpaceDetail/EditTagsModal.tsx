import { useState, KeyboardEvent, useEffect, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { X, Tag, Network, PencilLine } from "lucide-react";
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
    FileTag,
    KnowledgeSpaceTagLibraryTagItem,
    countSpaceNativeTags,
    isBoundLibraryTagName,
    getSpaceTagsApi,
    addSpaceTagApi,
    updateFileTagsApi,
    batchUpdateTagsApi,
    getBoundTagLibraryTagsForKnowledgeApi,
    getKnowledgeSpaceReviewTagVisibilityApi,
} from "~/api/knowledge";
import { useLocalize } from "~/hooks";
import { getFullWidthLength } from "~/utils";

interface EditTagsModalProps {
    isOpen: boolean;
    onClose: (confirmClose: boolean) => void;
    /**
     * Called after tags are saved successfully so parent can refresh.
     * In single-file mode the updated tag list is passed so the parent can
     * patch that file's tags in place instead of refetching the whole list.
     */
    onSaved?: (tags?: FileTag[]) => void;
    spaceId: string;
    /** Single file edit — mutually exclusive with fileIds */
    fileId?: string | null;
    /** Batch mode: list of file IDs to append tags */
    fileIds?: string[];
    /** Tags currently assigned to the file (for single-file mode) */
    initialTagIds?: number[];
}

function mergeRecommendedTags(items: KnowledgeSpaceTagLibraryTagItem[]): KnowledgeSpaceTagLibraryTagItem[] {
    const seen = new Set<string>();
    const merged: KnowledgeSpaceTagLibraryTagItem[] = [];
    for (const item of items) {
        const name = String(item.name ?? "").trim();
        if (!name) continue;
        const key = `${item.resource_type}:${name}`;
        if (seen.has(key)) continue;
        seen.add(key);
        merged.push({ ...item, name });
    }
    return merged;
}

function findSpaceTagByName(tags: SpaceTag[], name: string): SpaceTag | undefined {
    const normalized = name.trim().toLowerCase();
    return tags.find((tag) => tag.name.trim().toLowerCase() === normalized);
}

function isPendingReviewSpaceTag(tag: SpaceTag): boolean {
    return tag.review_status === 0;
}

function isApprovedSpaceTag(tag: SpaceTag): boolean {
    if (tag.review_status === undefined || tag.review_status === null) {
        return true;
    }
    // 1 = approved; 0 = pending; 2 = rejected
    return tag.review_status === 1;
}

function isApprovedRecommendedTag(item: KnowledgeSpaceTagLibraryTagItem, spaceTags: SpaceTag[]): boolean {
    const existing = findSpaceTagByName(spaceTags, item.name);
    return !!existing && isApprovedSpaceTag(existing);
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
    const [recommendedTags, setRecommendedTags] = useState<KnowledgeSpaceTagLibraryTagItem[]>([]);
    const [recommendedLoading, setRecommendedLoading] = useState(false);
    // IDs of tags selected for this file
    const [selectedTagIds, setSelectedTagIds] = useState<Set<number>>(new Set());
    // IDs of newly created manual tags that need review (picked during this dialog session)
    const [selectedReviewTagIds, setSelectedReviewTagIds] = useState<Set<number>>(new Set());
    const [inputValue, setInputValue] = useState("");
    const [loading, setLoading] = useState(false);
    const [spaceTagsLoading, setSpaceTagsLoading] = useState(false);
    const [reviewTagConfigLoading, setReviewTagConfigLoading] = useState(true);
    const [reviewTagEnabled, setReviewTagEnabled] = useState(false);
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();

    const isBatchMode = !!(fileIds && fileIds.length > 0);
    const spaceNativeTagCount = countSpaceNativeTags(spaceTags, recommendedTags);

    const isTagInputDisabled = reviewTagConfigLoading || !reviewTagEnabled;

    // Fetch space tags and bound tag-library tags when opened
    useEffect(() => {
        if (!isOpen || !spaceId) return;
        setInputValue("");
        setSelectedTagIds(new Set(initialTagIds));
        setSelectedReviewTagIds(new Set());
        setRecommendedTags([]);
        setRecommendedLoading(true);
        setSpaceTagsLoading(true);
        setReviewTagConfigLoading(true);
        setReviewTagEnabled(false);

        getKnowledgeSpaceReviewTagVisibilityApi()
            .then(({ enabled }) => setReviewTagEnabled(enabled))
            .catch(() => setReviewTagEnabled(false))
            .finally(() => setReviewTagConfigLoading(false));

        getSpaceTagsApi(spaceId)
            .then(setSpaceTags)
            .catch(() => {
                showToast({ message: localize("com_knowledge.fetch_tags_failed"), status: "error" });
            })
            .finally(() => setSpaceTagsLoading(false));

        getBoundTagLibraryTagsForKnowledgeApi(spaceId)
            .then((items) => setRecommendedTags(mergeRecommendedTags(items)))
            .catch(() => {
                setRecommendedTags([]);
            })
            .finally(() => setRecommendedLoading(false));
    }, [isOpen, spaceId]);

    // When review is off, drop pending/rejected tags from the current selection.
    useEffect(() => {
        if (!isOpen || reviewTagConfigLoading || spaceTagsLoading || reviewTagEnabled) return;

        setSelectedTagIds((prev) => {
            const approvedIds = [...prev].filter((id) => {
                const tag = spaceTags.find((item) => item.id === id);
                return tag && isApprovedSpaceTag(tag);
            });
            if (approvedIds.length === prev.size) return prev;
            return new Set(approvedIds);
        });
        setSelectedReviewTagIds(new Set());
    }, [isOpen, reviewTagConfigLoading, spaceTagsLoading, reviewTagEnabled, spaceTags]);

    const isRecommendedTagSelected = (item: KnowledgeSpaceTagLibraryTagItem) =>
        spaceTags.some(
            (tag) => tag.name.trim().toLowerCase() === item.name.trim().toLowerCase() && selectedTagIds.has(tag.id),
        );

    const canSelectRecommendedTag = (item: KnowledgeSpaceTagLibraryTagItem) => {
        if (spaceTagsLoading || recommendedLoading) return false;
        if (!reviewTagEnabled) {
            return isApprovedRecommendedTag(item, spaceTags);
        }
        return true;
    };

    const visibleRecommendedTags = useMemo(() => {
        if (reviewTagEnabled || reviewTagConfigLoading) {
            return recommendedTags;
        }
        if (spaceTagsLoading) {
            return [];
        }
        return recommendedTags.filter((item) => isApprovedRecommendedTag(item, spaceTags));
    }, [recommendedTags, reviewTagEnabled, reviewTagConfigLoading, spaceTagsLoading, spaceTags]);

    const recommendedTagsLoading =
        recommendedLoading || (!reviewTagEnabled && !reviewTagConfigLoading && spaceTagsLoading);

    const addTagToSelection = (tag: SpaceTag) => {
        if (!reviewTagEnabled && isPendingReviewSpaceTag(tag)) {
            showToast({ message: localize("com_knowledge.review_tag_feature_disabled"), status: "error" });
            return;
        }
        setSelectedTagIds((prev) => {
            if (prev.has(tag.id)) return prev;
            if (prev.size >= 10) {
                showToast({ message: localize("com_knowledge.tags_count_limit_exceeded"), status: "error" });
                return prev;
            }
            return new Set(prev).add(tag.id);
        });
        if (isPendingReviewSpaceTag(tag)) {
            setSelectedReviewTagIds((prev) => new Set(prev).add(tag.id));
        }
    };

    // Toggle a space tag selection
    const toggleTag = (tag: SpaceTag) => {
        if (!reviewTagEnabled && isPendingReviewSpaceTag(tag) && !selectedTagIds.has(tag.id)) {
            showToast({ message: localize("com_knowledge.review_tag_feature_disabled"), status: "error" });
            return;
        }
        setSelectedTagIds((prev) => {
            const next = new Set(prev);
            if (next.has(tag.id)) {
                next.delete(tag.id);
                if (isPendingReviewSpaceTag(tag)) {
                    setSelectedReviewTagIds((reviewPrev) => {
                        const reviewNext = new Set(reviewPrev);
                        reviewNext.delete(tag.id);
                        return reviewNext;
                    });
                }
            } else {
                if (next.size >= 10) {
                    showToast({ message: localize("com_knowledge.tags_count_limit_exceeded"), status: "error" });
                    return prev;
                }
                next.add(tag.id);
                if (isPendingReviewSpaceTag(tag)) {
                    setSelectedReviewTagIds((reviewPrev) => new Set(reviewPrev).add(tag.id));
                }
            }
            return next;
        });
    };

    const resolveCreateTagErrorMessage = (err: any) => {
        const statusCode = err?.status_code;
        if (statusCode) {
            const localized = localize(`api_errors.${statusCode}`);
            if (localized && localized !== `api_errors.${statusCode}`) {
                return localized;
            }
        }
        return err?.status_message || localize("com_knowledge.create_tag_failed");
    };

    const selectOrCreateSpaceTag = async (tagName: string, resourceType?: string) => {
        const trimmed = tagName.trim();
        if (!trimmed) return;

        const existing = findSpaceTagByName(spaceTags, trimmed);
        if (existing) {
            toggleTag(existing);
            return;
        }

        if (!reviewTagEnabled) {
            showToast({ message: localize("com_knowledge.review_tag_feature_disabled"), status: "error" });
            return;
        }

        const fromBoundLibrary = isBoundLibraryTagName(trimmed, recommendedTags);

        if (selectedTagIds.size >= 10) {
            showToast({ message: localize("com_knowledge.tags_count_limit_exceeded"), status: "error" });
            return;
        }

        if (!fromBoundLibrary && spaceNativeTagCount >= 50) {
            showToast({ message: localize("com_knowledge.space_tags_limit_exceeded"), status: "error" });
            return;
        }

        try {
            const newTag = await addSpaceTagApi(spaceId, trimmed);
            const enrichedTag: SpaceTag = {
                ...newTag,
                resource_type: resourceType || newTag.resource_type,
            };
            setSpaceTags((prev) => {
                if (findSpaceTagByName(prev, trimmed)) return prev;
                return [...prev, enrichedTag];
            });
            addTagToSelection(enrichedTag);
            queryClient.invalidateQueries({ queryKey: ["spaceTags", spaceId] });
        } catch (err: any) {
            if (err?.status_code === 18050) {
                try {
                    const refreshed = await getSpaceTagsApi(spaceId);
                    setSpaceTags(refreshed);
                    const refetched = findSpaceTagByName(refreshed, trimmed);
                    if (refetched) {
                        addTagToSelection(refetched);
                        return;
                    }
                } catch {
                    // fall through to toast
                }
            }
            showToast({ message: resolveCreateTagErrorMessage(err), status: "error" });
        }
    };

    const handleSelectRecommendedTag = async (item: KnowledgeSpaceTagLibraryTagItem) => {
        if (!canSelectRecommendedTag(item)) {
            showToast({ message: localize("com_knowledge.review_tag_feature_disabled"), status: "error" });
            return;
        }
        await selectOrCreateSpaceTag(item.name, item.resource_type);
    };

    // Enter key: create a new space tag, then select it
    const handleKeyDown = async (e: KeyboardEvent<HTMLInputElement>) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        if (reviewTagConfigLoading) return;
        if (!reviewTagEnabled) {
            showToast({ message: localize("com_knowledge.review_tag_feature_disabled"), status: "error" });
            return;
        }
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
        const existing = findSpaceTagByName(spaceTags, trimmed);
        if (existing) {
            addTagToSelection(existing);
            setInputValue("");
            return;
        }

        if (spaceNativeTagCount >= 50) {
            showToast({ message: localize("com_knowledge.space_tags_limit_exceeded"), status: "error" });
            return;
        }

        await selectOrCreateSpaceTag(trimmed);
        setInputValue("");
    };

    // Save: update file tags via API
    const handleSave = async () => {
        const pendingText = inputValue.trim();

        if (!reviewTagEnabled && selectedReviewTagIds.size > 0) {
            showToast({ message: localize("com_knowledge.review_tag_feature_disabled"), status: "error" });
            return;
        }

        setLoading(true);

        try {
            const tagIds = Array.from(selectedTagIds) as number[];
            const newReviewTagIds = Array.from(selectedReviewTagIds) as number[];
            if (isBatchMode && fileIds) {
                // Batch append mode
                await batchUpdateTagsApi(spaceId, {
                    file_ids: fileIds.map(Number),
                    tag_ids: tagIds,
                });
                showToast({ message: localize("com_knowledge.batch_add_tags_success"), status: "success" });
                // Batch mode spans multiple files — let the parent decide how to refresh.
                onSaved?.();
            } else if (fileId) {
                // Single file overwrite mode
                await updateFileTagsApi(spaceId, fileId, tagIds, newReviewTagIds);
                !pendingText && showToast({ message: localize("com_knowledge.tag_save_success"), status: "success" });
                // Hand the updated tag list back so the parent can patch this
                // file's tags in place without reloading the whole list.
                const savedTags: FileTag[] = spaceTags
                    .filter((t) => selectedTagIds.has(t.id))
                    .map((t) => ({ id: t.id, name: t.name }));
                onSaved?.(savedTags);
            }
            // Invalidate shared spaceTags cache so search dropdown picks up new tags
            queryClient.invalidateQueries({ queryKey: ["spaceTags", spaceId] });
            onClose(true);
        } catch {
            showToast({ message: localize("com_knowledge.tag_save_failed"), status: "error" });
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
    const selectedTags = spaceTags.filter(
        (tag) =>
            selectedTagIds.has(tag.id)
            && (reviewTagEnabled || reviewTagConfigLoading || isApprovedSpaceTag(tag)),
    );

    const systemTags = visibleRecommendedTags.filter(
        (t) => t.resource_type === "system_tag" || t.resource_type === "manual_tag",
    );
    const aiTags = visibleRecommendedTags.filter((t) => t.resource_type === "ai_auto_tag");
    const manualTags = visibleRecommendedTags.filter(
        (t) =>
            t.resource_type !== "system_tag"
            && t.resource_type !== "manual_tag"
            && t.resource_type !== "ai_auto_tag",
    );

    const renderRecommendedTagItem = (item: KnowledgeSpaceTagLibraryTagItem) => {
        const isSelected = isRecommendedTagSelected(item);
        const isClickable = canSelectRecommendedTag(item);
        return (
            <span
                key={`${item.resource_type}:${item.name}`}
                onClick={() => {
                    void handleSelectRecommendedTag(item);
                }}
                className={`px-2 h-7 flex items-center justify-center gap-1 text-[12px] leading-[20px] rounded-[4px] transition-colors ${isSelected
                    ? "text-[#165dff] cursor-default bg-primary/10"
                    : isClickable
                        ? "bg-[#f2f3f5] text-[#4e5969] hover:bg-[#e5e6eb] cursor-pointer"
                        : "bg-[#f2f3f5] text-[#c9cdd4] cursor-not-allowed"
                    }`}
            >
                {item.name}
            </span>
        );
    };

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
            <DialogContent
                onPointerDownOutside={(e) => e.preventDefault()}
                onInteractOutside={(e) => e.preventDefault()}
                className="flex w-[600px] flex-col items-stretch gap-0 rounded-xl border-none bg-white p-0 shadow-[0px_5px_22px_0px_rgba(61,68,110,0.2)] outline-none touch-mobile:inset-0 touch-mobile:left-0 touch-mobile:top-0 touch-mobile:h-dvh touch-mobile:w-screen touch-mobile:max-w-none touch-mobile:translate-x-0 touch-mobile:translate-y-0 touch-mobile:rounded-none [&>button]:hidden"
            >
                <DialogHeader className="h-auto shrink-0 space-y-0 border-b border-[#EBECF0] px-6 py-4 text-left touch-mobile:px-4 touch-mobile:pt-6 touch-mobile:pb-4">
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
                <div className="flex flex-1 flex-col gap-2 px-6 pt-5 pb-5 touch-mobile:px-4 touch-mobile:pt-5 touch-mobile:pb-5">
                {reviewTagEnabled && (
                    <div className="flex items-start gap-0.5 text-[12px] leading-5 text-[#F53F3F]">
                        <span className="shrink-0">***</span>
                        <span>{localize("com_knowledge.manual_tag_review_hint")}</span>
                    </div>
                )}
                {!reviewTagEnabled && !reviewTagConfigLoading && (
                    <div className="flex items-start gap-0.5 text-[12px] leading-5 text-[#86909c]">
                        <span>{localize("com_knowledge.review_tag_input_disabled_placeholder")}</span>
                    </div>
                )}
                <div className="flex flex-1 flex-col gap-0.5">
                    {/* Tags Input Box */}
                    <div
                        className={`relative flex min-h-8 flex-wrap items-center gap-1 rounded-[8px] border border-[#EBECF0] bg-white px-3 py-[5px] pr-[40px] transition-colors ${isTagInputDisabled ? "cursor-not-allowed bg-[#f7f8fa]" : "cursor-text focus-within:border-primary"}`}
                        onClick={() => {
                            if (isTagInputDisabled) return;
                            document.getElementById("tag-input")?.focus();
                        }}
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
                            onChange={(e) => {
                                if (isTagInputDisabled) return;
                                setInputValue(e.target.value);
                            }}
                            onKeyDown={handleKeyDown}
                            disabled={reviewTagConfigLoading}
                            readOnly={!reviewTagEnabled && !reviewTagConfigLoading}
                            placeholder={
                                reviewTagConfigLoading
                                    ? localize("com_knowledge.loading")
                                    : selectedTags.length === 0 && !inputValue
                                        ? reviewTagEnabled
                                            ? localize("com_knowledge.input_tags_placeholder")
                                            : localize("com_knowledge.review_tag_input_disabled_placeholder")
                                        : ""
                            }
                            className="flex-1 min-w-[120px] bg-transparent outline-none text-sm leading-[22px] text-[#212121] placeholder-[#86909c] min-h-[22px] disabled:cursor-not-allowed disabled:text-[#c9cdd4]"
                        // maxLength={8}
                        />
                        <span className="absolute right-3 top-0 flex h-full items-center text-[14px] leading-[22px] text-[#999]">
                            {selectedTagIds.size}/10
                        </span>
                    </div>

                    {/* 推荐标签 */}
                    <div className="flex flex-col gap-3 pt-1">
                        <div className="text-[14px] leading-5 font-medium text-[#212121]">{localize("com_knowledge.recommended_tags")}</div>
                        {recommendedTagsLoading && (
                            <span className="text-[12px] text-[#86909c]">{localize("com_knowledge.loading")}</span>
                        )}
                        {!recommendedTagsLoading && visibleRecommendedTags.length === 0 && (
                            <span className="text-[12px] text-[#86909c]">{localize("com_knowledge.no_tags")}</span>
                        )}
                        {!recommendedTagsLoading && systemTags.length > 0 && (
                            <div className="flex flex-col gap-1.5">
                                <div className="flex items-center gap-1 text-[12px] leading-5 text-[#86909c]">
                                    <Network className="size-3.5 shrink-0" />
                                    <span>{localize("com_knowledge.tag_type_system")}</span>
                                </div>
                                <div className="flex flex-wrap items-center gap-1">
                                    {systemTags.map(renderRecommendedTagItem)}
                                </div>
                            </div>
                        )}
                        {!recommendedTagsLoading && aiTags.length > 0 && (
                            <div className="flex flex-col gap-1.5">
                                <div className="flex items-center gap-1 text-[12px] leading-5 text-[#86909c]">
                                    <Tag className="size-3.5 shrink-0" />
                                    <span>{localize("com_knowledge.tag_type_ai")}</span>
                                </div>
                                <div className="flex flex-wrap items-center gap-1">
                                    {aiTags.map(renderRecommendedTagItem)}
                                </div>
                            </div>
                        )}
                        {!recommendedTagsLoading && manualTags.length > 0 && (
                            <div className="flex flex-col gap-1.5">
                                <div className="flex items-center gap-1 text-[12px] leading-5 text-[#86909c]">
                                    <PencilLine className="size-3.5 shrink-0" />
                                    <span>{localize("com_knowledge.tag_type_manual")}</span>
                                </div>
                                <div className="flex flex-wrap items-center gap-1">
                                    {manualTags.map(renderRecommendedTagItem)}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
                </div>

                <DialogFooter className="flex h-16 shrink-0 items-center justify-end gap-3 border-t border-[#EBECF0] px-6 py-3 touch-mobile:!mt-auto touch-mobile:!h-auto touch-mobile:!flex-row touch-mobile:!justify-stretch touch-mobile:px-4 touch-mobile:py-3 sm:space-x-0">
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
