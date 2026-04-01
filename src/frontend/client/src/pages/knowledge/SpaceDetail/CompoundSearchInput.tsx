import React, { useState, useRef, useEffect } from 'react';
import { Search, X, ChevronDown } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import {
    DropdownMenu,
    DropdownMenuTrigger,
    DropdownMenuContent,
    DropdownMenuItem
} from '~/components/ui/DropdownMenu';
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
    onActiveChange?: (active: boolean) => void;
}

export function CompoundSearchInput({ spaceId, isRoot = false, onSearch, className, onActiveChange }: CompoundSearchInputProps) {
    const localize = useLocalize();
  const [scope, setScope] = useState<'current' | 'all'>('current');
    const [selectedTags, setSelectedTags] = useState<SpaceTag[]>([]);
    const [keyword, setKeyword] = useState('');
    const [isFocused, setIsFocused] = useState(false);

    const containerRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);

    // Fetch space tags via react-query so cache is shared with EditTagsModal
    const { data: spaceTags = [] } = useQuery({
        queryKey: ['spaceTags', spaceId],
        queryFn: () => getSpaceTagsApi(spaceId),
        enabled: !!spaceId,
    });

    useEffect(() => {
        setScope(isRoot ? 'all' : 'current');
    }, [isRoot]);

    // Reset search state when switching to a different space
    useEffect(() => {
        setSelectedTags([]);
        setKeyword('');
        setIsFocused(false);
    }, [spaceId]);

    // Handle clicking outside to close the dropdown
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setIsFocused(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    useEffect(() => {
        onActiveChange?.(isFocused);
    }, [isFocused, onActiveChange]);

    const isSearching = selectedTags.length > 0 || keyword.trim().length > 0;

    const fireSearch = (tags: SpaceTag[], kw: string) => {
        onSearch?.({
            scope: isRoot ? 'all' : scope,
            tagIds: tags.map((t) => t.id),
            keyword: kw,
        });
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            fireSearch(selectedTags, keyword);
            setIsFocused(false);
            inputRef.current?.blur();
        } else if (e.key === 'Backspace' && keyword === '' && selectedTags.length > 0) {
            const newTags = selectedTags.slice(0, -1);
            setSelectedTags(newTags);
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
        <div ref={containerRef} className={cn("relative w-full", className)}>
            <div
                className={cn(
                    "flex flex-wrap items-center w-full min-h-[32px] bg-white border rounded-md transition-all px-3 py-1 gap-1",
                    isFocused ? "border-primary ring-1 ring-primary/20" : "border-[#e5e6eb] hover:border-primary/50"
                )}
                onClick={() => {
                    inputRef.current?.focus();
                    setIsFocused(true);
                }}
            >
                <Search className="size-4 text-[#86909c] shrink-0" />

                {/* Scope Select (Only if not at root) */}
                {!isRoot && (
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <button className="flex items-center gap-1 h-5 text-sm text-[#4e5969] hover:bg-gray-100 px-1 py-0.5 rounded cursor-pointer transition-colors max-w-[120px] shrink-0 outline-none">
                                <span className="truncate">{scopeLabel}</span>
                                <ChevronDown className="size-3 shrink-0" />
                            </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start" className="min-w-[120px]">
                            <DropdownMenuItem onClick={(e) => { e.stopPropagation(); setScope('current'); inputRef.current?.focus(); }}>{localize("com_knowledge.current_location")}</DropdownMenuItem>
                            <DropdownMenuItem onClick={(e) => { e.stopPropagation(); setScope('all'); inputRef.current?.focus(); }}>{localize("com_knowledge.current_space")}</DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}

                {/* Selected Tags */}
                {selectedTags.map((tag) => (
                    <div key={tag.id} className="flex items-center h-[22px] gap-1 bg-[#f2f3f5] text-[#4e5969] text-sm px-2 py-1 rounded truncate max-w-[100px] shrink-0">
                        {tag.name}
                        <X
                            className="size-3 text-[#86909c] hover:text-[#4e5969] cursor-pointer shrink-0"
                            onClick={(e) => {
                                e.stopPropagation();
                                handleRemoveTag(tag.id);
                            }}
                        />
                    </div>
                ))}

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
                    placeholder={selectedTags.length === 0 ? localize("com_knowledge.search_in_current_space") : ""}
                    className="flex-1 min-w-[50px] bg-transparent outline-none text-[13px] text-[#1d2129] placeholder:text-[#86909c] h-[22px]"
                    onFocus={() => setIsFocused(true)}
                />

                {/* Clear button */}
                {isSearching && (
                    <button
                        className="ml-auto w-4 h-4 rounded-full bg-[#f2f3f5] flex items-center justify-center hover:bg-[#e5e6eb] shrink-0 transition-colors"
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
            {isFocused && (
                <div className="absolute top-full left-0 mt-1 min-w-[320px] max-w-full bg-white border border-[#e5e6eb] shadow-[0_4px_10px_rgba(0,0,0,0.1)] rounded-md z-50 p-3">
                    <div className="text-sm font-medium text-gray-800 mb-2">{localize("com_knowledge.existing_tags")}</div>
                    <div className="flex flex-wrap gap-2">
                        {spaceTags.length === 0 && (
                            <span className="text-sm text-[#86909c]">{localize("com_knowledge.no_tags")}</span>
                        )}
                        {spaceTags.map((tag) => {
                            const isSelected = selectedTags.some((t) => t.id === tag.id);
                            return (
                                <button
                                    key={tag.id}
                                    className={cn(
                                        "px-2 rounded text-sm transition-colors border outline-none",
                                        isSelected
                                            ? "bg-primary/10 text-primary border-transparent cursor-default"
                                            : "bg-[#f2f3f5] text-[#4e5969] border-[#f2f3f5] hover:bg-[#e5e6eb]"
                                    )}
                                    onClick={(e) => {
                                        e.preventDefault();
                                        e.stopPropagation();
                                        if (!isSelected) handleAddTag(tag);
                                    }}
                                    disabled={isSelected || selectedTags.length >= 5}
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
