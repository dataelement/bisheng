import React, { useState, useRef, useEffect } from 'react';
import { Search, X, ChevronDown } from 'lucide-react';
import {
    DropdownMenu,
    DropdownMenuTrigger,
    DropdownMenuContent,
    DropdownMenuItem
} from '~/components/ui/DropdownMenu';
import { cn } from '~/utils';

export interface CompoundSearchInputProps {
    isRoot?: boolean;
    onSearch?: (params: { scope: 'current' | 'all', tags: string[], keyword: string }) => void;
    className?: string;
}

const ALL_TAGS = ["国际", "进出口", "大豆油", "政策", "水稻", "粮食"];

export function CompoundSearchInput({ isRoot = false, onSearch, className }: CompoundSearchInputProps) {
    const [scope, setScope] = useState<'current' | 'all'>('current');
    const [tags, setTags] = useState<string[]>([]);
    const [keyword, setKeyword] = useState('');
    const [isFocused, setIsFocused] = useState(false);

    const containerRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        if (isRoot) setScope('all');
    }, [isRoot]);

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

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter') {
            onSearch?.({ scope: isRoot ? 'all' : scope, tags, keyword });
            setIsFocused(false);
            inputRef.current?.blur();
        } else if (e.key === 'Backspace' && keyword === '' && tags.length > 0) {
            setTags(tags.slice(0, -1));
        }
    };

    const handleAddTag = (tag: string) => {
        if (tags.length < 5 && !tags.includes(tag)) {
            const newTags = [...tags, tag];
            setTags(newTags);
            // immediately trigger search
            onSearch?.({ scope: isRoot ? 'all' : scope, tags: newTags, keyword });
            inputRef.current?.focus();
            setIsFocused(true);
        }
    };

    const handleRemoveTag = (tagToRemove: string) => {
        const newTags = tags.filter(t => t !== tagToRemove);
        setTags(newTags);
        onSearch?.({ scope: isRoot ? 'all' : scope, tags: newTags, keyword });
        inputRef.current?.focus();
    };

    const handleClearAll = () => {
        setTags([]);
        setKeyword('');
        setIsFocused(false);
        onSearch?.({ scope: isRoot ? 'all' : scope, tags: [], keyword: '' });
    };

    const scopeLabel = scope === 'current' ? '当前位置' : '当前知识空间';

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
                            <DropdownMenuItem onClick={(e) => { e.stopPropagation(); setScope('current'); inputRef.current?.focus(); }}>当前位置</DropdownMenuItem>
                            <DropdownMenuItem onClick={(e) => { e.stopPropagation(); setScope('all'); inputRef.current?.focus(); }}>当前知识空间</DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}

                {/* Tags */}
                {tags.map(tag => (
                    <div key={tag} className="flex items-center h-[22px] gap-1 bg-[#f2f3f5] text-[#4e5969] text-sm px-2 py-1 rounded truncate max-w-[100px] shrink-0">
                        {tag}
                        <X
                            className="size-3 text-[#86909c] hover:text-[#4e5969] cursor-pointer shrink-0"
                            onClick={(e) => {
                                e.stopPropagation();
                                handleRemoveTag(tag);
                            }}
                        />
                    </div>
                ))}

                <input
                    ref={inputRef}
                    type="text"
                    value={keyword}
                    onChange={(e) => setKeyword(e.target.value)}
                    onKeyDown={handleKeyDown}
                    maxLength={100}
                    placeholder={tags.length === 0 ? "在当前知识空间进行搜索" : ""}
                    className="flex-1 min-w-[50px] bg-transparent outline-none text-[13px] text-[#1d2129] placeholder:text-[#86909c] h-[22px]"
                    onFocus={() => setIsFocused(true)}
                />

                {/* Clear button */}
                {(keyword || tags.length > 0) && (
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

            {/* Dropdown Panel */}
            {isFocused && (
                <div className="absolute top-full left-0 mt-1 min-w-[320px] max-w-full bg-white border border-[#e5e6eb] shadow-[0_4px_10px_rgba(0,0,0,0.1)] rounded-md z-50 p-3">
                    <div className="text-sm font-medium text-gray-800 mb-2">已有标签</div>
                    <div className="flex flex-wrap gap-2">
                        {ALL_TAGS.map(tag => {
                            const isSelected = tags.includes(tag);
                            return (
                                <button
                                    key={tag}
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
                                    disabled={isSelected || tags.length >= 5}
                                    type="button"
                                >
                                    {tag}
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}
