import { useMemo, useState } from "react";
import { Network, PencilLine, Search, Tag } from "lucide-react";
import { Button } from "~/components/ui";
import { Popover, PopoverContent, PopoverTrigger } from "~/components/ui/Popover";
import type { KnowledgeSpaceTagLibraryTagItem } from "~/api/knowledge";
import { useLocalize } from "~/hooks";

interface LibraryTagPickerProps {
    systemTags: KnowledgeSpaceTagLibraryTagItem[];
    aiTags: KnowledgeSpaceTagLibraryTagItem[];
    manualTags: KnowledgeSpaceTagLibraryTagItem[];
    loading: boolean;
    renderItem: (item: KnowledgeSpaceTagLibraryTagItem) => React.ReactNode;
}

function filterLibraryTags(
    tags: KnowledgeSpaceTagLibraryTagItem[],
    query: string,
): KnowledgeSpaceTagLibraryTagItem[] {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
        return tags;
    }
    const matched = tags.filter((tag) => tag.name.trim().toLowerCase().includes(normalized));
    return matched.sort((left, right) => {
        const leftName = left.name.trim().toLowerCase();
        const rightName = right.name.trim().toLowerCase();
        const leftPrefix = leftName.startsWith(normalized) ? 0 : 1;
        const rightPrefix = rightName.startsWith(normalized) ? 0 : 1;
        if (leftPrefix !== rightPrefix) {
            return leftPrefix - rightPrefix;
        }
        return leftName.localeCompare(rightName, "zh");
    });
}

export function LibraryTagPicker({
    systemTags,
    aiTags,
    manualTags,
    loading,
    renderItem,
}: LibraryTagPickerProps) {
    const localize = useLocalize();
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState("");
    const hasTags = systemTags.length + aiTags.length + manualTags.length > 0;
    const visibleSystemTags = useMemo(() => filterLibraryTags(systemTags, query), [systemTags, query]);
    const visibleAiTags = useMemo(() => filterLibraryTags(aiTags, query), [aiTags, query]);
    const visibleManualTags = useMemo(() => filterLibraryTags(manualTags, query), [manualTags, query]);
    const hasVisibleTags = visibleSystemTags.length + visibleAiTags.length + visibleManualTags.length > 0;
    const trimmedQuery = query.trim();

    const handleOpenChange = (nextOpen: boolean) => {
        setOpen(nextOpen);
        if (!nextOpen) {
            setQuery("");
        }
    };

    return (
        <Popover open={open} onOpenChange={handleOpenChange}>
            <PopoverTrigger asChild>
                <Button
                    type="button"
                    variant="outline"
                    className="h-7 rounded-[6px] px-3 text-[12px] font-normal"
                    disabled={loading || !hasTags}
                >
                    {localize("com_knowledge.pick_library_tags")}
                </Button>
            </PopoverTrigger>
            <PopoverContent
                align="end"
                side="bottom"
                sideOffset={8}
                collisionPadding={16}
                data-testid="library-tag-picker"
                className="z-[110] flex w-[min(360px,calc(100vw-32px))] max-h-[min(420px,60vh)] flex-col overflow-hidden border border-[#EBECF0] bg-white p-3 shadow-[0px_5px_22px_0px_rgba(61,68,110,0.2)] pointer-events-auto"
            >
                <div className="relative mb-3 shrink-0">
                    <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-[#86909c]" />
                    <input
                        type="text"
                        value={query}
                        autoFocus
                        aria-label={localize("com_knowledge.search_library_tags_placeholder")}
                        placeholder={localize("com_knowledge.search_library_tags_placeholder")}
                        className="h-8 w-full rounded-[6px] border border-[#EBECF0] bg-white pl-8 pr-3 text-[12px] leading-5 text-[#212121] outline-none placeholder:text-[#86909c] focus:border-primary"
                        onChange={(event) => setQuery(event.target.value)}
                        onKeyDown={(event) => event.stopPropagation()}
                    />
                </div>
                <div
                    className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain"
                    // Nested in EditTagsModal's Dialog: the portaled popover sits
                    // outside react-remove-scroll's shard, so wheel is preventDefault'd
                    // at document. Dragging the scrollbar still works; drive scrollTop
                    // here so the mouse wheel can move the tag list.
                    onWheel={(event) => {
                        event.currentTarget.scrollTop += event.deltaY;
                    }}
                >
                    {loading && (
                        <span className="text-[12px] text-[#86909c]">{localize("com_knowledge.loading")}</span>
                    )}
                    {!loading && !hasTags && (
                        <span className="text-[12px] text-[#86909c]">{localize("com_knowledge.no_tags")}</span>
                    )}
                    {!loading && hasTags && !hasVisibleTags && (
                        <span className="text-[12px] text-[#86909c]">
                            {trimmedQuery
                                ? localize("com_knowledge.no_matching_library_tags")
                                : localize("com_knowledge.no_tags")}
                        </span>
                    )}
                    {!loading && visibleSystemTags.length > 0 && (
                        <div className="flex flex-col gap-1.5">
                            <div className="flex items-center gap-1 text-[12px] leading-5 text-[#86909c]">
                                <Network className="size-3.5 shrink-0" />
                                <span>{localize("com_knowledge.tag_type_system")}</span>
                            </div>
                            <div className="flex flex-wrap items-center gap-1">
                                {visibleSystemTags.map(renderItem)}
                            </div>
                        </div>
                    )}
                    {!loading && visibleAiTags.length > 0 && (
                        <div className="flex flex-col gap-1.5">
                            <div className="flex items-center gap-1 text-[12px] leading-5 text-[#86909c]">
                                <Tag className="size-3.5 shrink-0" />
                                <span>{localize("com_knowledge.tag_type_ai")}</span>
                            </div>
                            <div className="flex flex-wrap items-center gap-1">
                                {visibleAiTags.map(renderItem)}
                            </div>
                        </div>
                    )}
                    {!loading && visibleManualTags.length > 0 && (
                        <div className="flex flex-col gap-1.5">
                            <div className="flex items-center gap-1 text-[12px] leading-5 text-[#86909c]">
                                <PencilLine className="size-3.5 shrink-0" />
                                <span>{localize("com_knowledge.tag_type_manual")}</span>
                            </div>
                            <div className="flex flex-wrap items-center gap-1">
                                {visibleManualTags.map(renderItem)}
                            </div>
                        </div>
                    )}
                </div>
            </PopoverContent>
        </Popover>
    );
}
