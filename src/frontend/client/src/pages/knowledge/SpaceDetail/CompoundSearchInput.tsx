import React, { useState, useRef, useEffect, useCallback } from 'react';
import { X, ChevronDown } from 'lucide-react';
import { Outlined } from 'bisheng-icons';
import {
    DropdownMenu,
    DropdownMenuTrigger,
    DropdownMenuContent,
    DropdownMenuItem
} from '~/components/ui/DropdownMenu';
import { knowledgeSpaceDropdownSurfaceClassName } from '~/components/SidebarListMoreMenu';
import { cn } from '~/utils';
import { SpaceTag, getSpaceTagsApi } from '~/api/knowledge';
import { useLocalize } from "~/hooks";

export interface SearchParams {
    scope: 'current' | 'all';
    tagIds: number[];
    keyword: string;
}

export interface CompoundSearchInputProps {
    spaceId: string;
    isRoot?: boolean;
    onSearch?: (params: SearchParams) => void;
    className?: string;
    /** Render as a single search-icon button that expands into the full field on click. */
    collapsible?: boolean;
}

export function CompoundSearchInput({ spaceId, isRoot = false, onSearch, className, collapsible = false }: CompoundSearchInputProps) {
    const localize = useLocalize();
    const [scope, setScope] = useState<'current' | 'all'>('current');
    const [selectedTags, setSelectedTags] = useState<SpaceTag[]>([]);
    const [keyword, setKeyword] = useState('');
    const [isFocused, setIsFocused] = useState(false);
    const [isScopeMenuOpen, setIsScopeMenuOpen] = useState(false);
    const [spaceTags, setSpaceTags] = useState<SpaceTag[]>([]);

    // The search field is "expanded" whenever the user is interacting with it,
    // either via input focus / tag dropdown or the scope DropdownMenu. The parent
    // toolbar reads this via has-[[data-expanded=true]] to keep its width stable
    // even when Radix portals the menu out of the focus tree.
    const isExpanded = isFocused || isScopeMenuOpen;

    const containerRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const debounceTimerRef = useRef<number | null>(null);

    useEffect(() => {
        setScope(isRoot ? 'all' : 'current');
    }, [isRoot]);

    // Fetch space tags from API
    const refreshTags = useCallback(() => {
        if (!spaceId) return;
        getSpaceTagsApi(spaceId).then(setSpaceTags).catch(() => { });
    }, [spaceId]);

    // Reset search state when switching to a different space
    useEffect(() => {
        setSelectedTags([]);
        setKeyword('');
        setIsFocused(false);
        setSpaceTags([]);
        refreshTags();
    }, [spaceId, refreshTags]);

    // Handle clicking outside to close the dropdown.
    // While the scope DropdownMenu is open its portaled content lives outside
    // containerRef — skip the reset so the search field doesn't collapse.
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (isScopeMenuOpen) return;
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setIsFocused(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [isScopeMenuOpen]);

    const isSearching = selectedTags.length > 0 || keyword.trim().length > 0;

    // Collapsed: show only the search icon until the user focuses it or has an active query.
    const collapsed = collapsible && !isExpanded && !isSearching;

    const fireSearch = (tags: SpaceTag[], kw: string) => {
        onSearch?.({
            scope: isRoot ? 'all' : scope,
            tagIds: tags.map((t) => t.id),
            keyword: kw,
        });
    };

    useEffect(() => {
        if (debounceTimerRef.current) {
            window.clearTimeout(debounceTimerRef.current);
            debounceTimerRef.current = null;
        }
        // Keep clear behavior immediate when keyword is empty and no tags.
        if (keyword.trim() === '' && selectedTags.length === 0) {
            return;
        }
        debounceTimerRef.current = window.setTimeout(() => {
            fireSearch(selectedTags, keyword);
            debounceTimerRef.current = null;
        }, 300);
        return () => {
            if (debounceTimerRef.current) {
                window.clearTimeout(debounceTimerRef.current);
                debounceTimerRef.current = null;
            }
        };
    }, [keyword, scope, isRoot]);

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            fireSearch(selectedTags, keyword);
            setIsFocused(false);
            inputRef.current?.blur();
        }
    };

    // Click a tag in the dropdown → select it and immediately search
    const handleAddTag = (tag: SpaceTag) => {
        if (selectedTags.length >= 5 || selectedTags.some((t) => t.id === tag.id)) return;
        const newTags = [...selectedTags, tag];
        setSelectedTags(newTags);
        fireSearch(newTags, keyword);
        inputRef.current?.focus();
        setIsFocused(true);
    };

    const handleRemoveTag = (tagId: number) => {
        const newTags = selectedTags.filter((t) => t.id !== tagId);
        setSelectedTags(newTags);
        fireSearch(newTags, keyword);
        inputRef.current?.focus();
    };

    const handleClearAll = () => {
        setSelectedTags([]);
        setKeyword('');
        setIsFocused(false);
        onSearch?.({ scope: isRoot ? 'all' : scope, tagIds: [], keyword: '' });
    };

    const scopeLabel = scope === 'current' ? localize("com_knowledge.current_location") : localize("com_knowledge.current_space");

    return (
        <div
            ref={containerRef}
            data-expanded={isExpanded ? 'true' : 'false'}
            className={cn(
                "relative",
                collapsible
                    ? cn(
                        "shrink-0 transition-[width] duration-200 ease-out",
                        collapsed ? "w-8" : "w-[min(340px,60vw)] sm:w-[340px]"
                    )
                    : "w-full",
                className
            )}
        >
            <div
                className={cn(
                    "flex flex-nowrap items-center w-full h-8 min-h-8 max-h-8 overflow-hidden",
                    "bg-white border rounded-md",
                    collapsible
                        ? cn(
                            // Animate gap so icon → input transition feels continuous, not snapped.
                            "transition-[gap,background-color,border-color,box-shadow] duration-200 ease-out px-2",
                            collapsed ? "gap-0 cursor-pointer" : "gap-1"
                        )
                        : "gap-1 px-2 sm:px-3 transition-[border-color,box-shadow]",
                    // Active state per Figma 11495:16479 — gray border + gray ring (not blue).
                    // Collapsed = behaves like the sibling icon buttons (bg change on hover, border steady);
                    // expanded = behaves like an input field (border darkens on hover before focus).
                    isFocused
                        ? "border-[#ddd] shadow-[0_0_0_2px_#f1f5f9]"
                        : collapsed
                            ? "border-[#e5e6eb] hover:bg-[#f7f8fa]"
                            : "border-[#e5e6eb] hover:border-[#ddd]"
                )}
                onClick={() => {
                    inputRef.current?.focus();
                    if (!isFocused) refreshTags();
                    setIsFocused(true);
                }}
            >
                <Outlined.Search className="size-4 text-[#818181] shrink-0" />

                {/* 范围选择：仅在输入框聚焦（或菜单已打开）时显示，高亮表示已选范围；仅文案随 current / all 切换 */}
                {!isRoot && isExpanded && (
                    <DropdownMenu open={isScopeMenuOpen} onOpenChange={setIsScopeMenuOpen}>
                        <DropdownMenuTrigger asChild>
                            <button
                                type="button"
                                className="flex items-center gap-1 h-6 max-w-[min(120px,40vw)] shrink-0 rounded px-2 text-sm outline-none transition-colors bg-[#F7F7F7] text-[#212121] hover:bg-[#F1F1F1]"
                                onClick={(e) => e.stopPropagation()}
                            >
                                <span className="truncate">{scopeLabel}</span>
                                <ChevronDown className="size-3 shrink-0 opacity-80" />
                            </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent
                            align="start"
                            className={cn('min-w-[120px]', knowledgeSpaceDropdownSurfaceClassName)}
                        >
                            <DropdownMenuItem onClick={(e) => { e.stopPropagation(); setScope('current'); inputRef.current?.focus(); setIsFocused(true); }}>{localize("com_knowledge.current_location")}</DropdownMenuItem>
                            <DropdownMenuItem onClick={(e) => { e.stopPropagation(); setScope('all'); inputRef.current?.focus(); setIsFocused(true); }}>{localize("com_knowledge.current_space")}</DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}

                <input
                    ref={inputRef}
                    type="text"
                    value={keyword}
                    onChange={(e) => {
                        const newVal = e.target.value;
                        setKeyword(newVal);
                        // Auto-exit search mode when input is cleared and no tags are selected
                        if (newVal === '' && selectedTags.length === 0) {
                            fireSearch([], '');
                        }
                    }}
                    onKeyDown={handleKeyDown}
                    maxLength={100}
                    placeholder={collapsed ? "" : localize("com_knowledge.search_in_current_space")}
                    className={cn(
                        "min-w-0 bg-transparent outline-none text-[13px] text-[#1d2129] placeholder:text-[#86909c] h-[22px]",
                        collapsed ? "w-0 flex-none p-0" : "flex-1 min-w-[50px]"
                    )}
                    onFocus={() => { if (!isFocused) refreshTags(); setIsFocused(true); }}
                />

                {/* Clear button */}
                {isSearching && (
                    <button
                        className="ml-auto w-4 h-4 rounded-full bg-[#f2f3f5] flex items-center justify-center hover:bg-[#e5e6eb] shrink-0 transition-colors"
                        onMouseDown={(e) => {
                            // Keep input focused to avoid focus-within width flicker.
                            e.preventDefault();
                        }}
                        onClick={(e) => {
                            e.stopPropagation();
                            handleClearAll();
                        }}
                        type="button"
                    >
                        <X className="size-3 text-[#86909c]" />
                    </button>
                )}
            </div>

            {/* Dropdown Panel — space tags */}
            {isFocused && !isScopeMenuOpen && (
                <div className="absolute top-full left-0 mt-1 min-w-[320px] max-w-full bg-white shadow-[0_4px_10px_rgba(0,0,0,0.1)] rounded-md z-50 p-3 max-[767px]:min-w-0 max-[767px]:w-full">
                    <div className="text-sm font-medium text-gray-800 mb-2">{localize("com_knowledge.existing_tags")}</div>
                    <div className="flex flex-wrap gap-2">
                        {spaceTags.length === 0 && (
                            <span className="text-sm text-[#86909c]">{localize("com_knowledge.no_tags")}</span>
                        )}
                        {spaceTags.map((tag) => {
                            const isSelected = selectedTags.some((t) => t.id === tag.id);
                            const atLimit = !isSelected && selectedTags.length >= 5;
                            return (
                                <button
                                    key={tag.id}
                                    className={cn(
                                        "px-2 rounded text-sm transition-colors border outline-none",
                                        isSelected
                                            ? "bg-primary/10 text-primary border-transparent hover:bg-primary/15"
                                            : "bg-[#f2f3f5] text-[#4e5969] border-[#f2f3f5] hover:bg-[#e5e6eb]",
                                        atLimit && "opacity-50 cursor-not-allowed hover:bg-[#f2f3f5]"
                                    )}
                                    onMouseDown={(e) => {
                                        // Keep focus on input to avoid focus-within width flicker.
                                        e.preventDefault();
                                    }}
                                    onClick={(e) => {
                                        e.preventDefault();
                                        e.stopPropagation();
                                        if (isSelected) {
                                            handleRemoveTag(tag.id);
                                        } else if (!atLimit) {
                                            handleAddTag(tag);
                                        }
                                    }}
                                    disabled={atLimit}
                                    type="button"
                                >
                                    {tag.name}
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}
