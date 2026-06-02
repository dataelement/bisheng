import React, { useLayoutEffect, useRef, useState, ReactNode } from 'react';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '~/components/ui/Tooltip2';
import { FileTag } from '~/api/knowledge';
import { cn } from '~/utils';

type TagVariant = 'pill' | 'text';

interface TagGroupProps {
    tags: FileTag[];
    actionButton?: ReactNode;
    /**
     * Visual style.
     * - `pill` (default): grey rounded background — used in the list view.
     * - `text`: plain `#tag` 10px grey text — used in the card view (Figma 11671:34378).
     */
    variant?: TagVariant;
    /**
     * Tag IDs hit by the active search. Matching tags render in the highlight
     * color (Figma 11814:70449) so users can see which tags satisfied the query
     * when a file has additional non-matching tags.
     */
    highlightedTagIds?: number[];
}

const VARIANT_STYLES: Record<TagVariant, {
    container: string;
    tag: string;
    tagHighlighted: string;
    tagFirst: string;
    moreBadge: string;
    measure: string;
    /** Estimated width of the "+N" badge incl. surrounding gap, used by overflow calc. */
    moreBadgeReserve: number;
}> = {
    pill: {
        container: 'min-h-[24px] gap-1.5',
        tag: 'bg-[#f2f3f5] text-[#4e5969] text-xs px-1.5 py-0.5 rounded-sm',
        tagHighlighted: 'bg-[#E6EDFC] text-[#3a74e9] font-semibold text-xs px-1.5 py-0.5 rounded-sm',
        tagFirst: 'min-w-[30px] truncate flex-shrink',
        moreBadge: 'bg-[#f2f3f5] text-[#4e5969] font-medium text-xs px-1.5 py-0.5 rounded-sm cursor-pointer flex-shrink-0',
        measure: 'px-1.5 py-0.5 text-xs',
        moreBadgeReserve: 40,
    },
    text: {
        container: 'min-h-[20px] gap-1',
        tag: 'text-[10px] leading-5 text-[#999] whitespace-nowrap',
        tagHighlighted: 'text-[10px] leading-5 font-semibold text-[#3a74e9] whitespace-nowrap',
        tagFirst: 'min-w-[20px] truncate flex-shrink',
        moreBadge: 'text-[10px] leading-5 text-[#999] cursor-pointer flex-shrink-0',
        measure: 'text-[10px] leading-5',
        moreBadgeReserve: 24,
    },
};

const TagGroup = ({ tags, actionButton, variant = 'pill', highlightedTagIds }: TagGroupProps) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const [visibleCount, setVisibleCount] = useState(1); // Initial fallback
    const styles = VARIANT_STYLES[variant];
    const renderTagText = (tag: FileTag) => variant === 'text' ? `#${tag.name}` : tag.name;
    const highlightSet = React.useMemo(
        () => new Set(highlightedTagIds ?? []),
        [highlightedTagIds],
    );
    const tagClass = (tag: FileTag) => highlightSet.has(tag.id) ? styles.tagHighlighted : styles.tag;

    useLayoutEffect(() => {
        const calculateVisibleTags = () => {
            if (!containerRef.current) return;

            const containerWidth = containerRef.current.offsetWidth;
            const tagElements = containerRef.current.querySelectorAll('.tag-measure') as NodeListOf<HTMLElement>;
            const gap = variant === 'text' ? 4 : 6;
            const actionBtnWidth = actionButton ? 28 : 0;

            let currentWidth = (tagElements[0]?.offsetWidth || 0) + gap;
            let count = 1;

            for (let i = 1; i < tagElements.length; i++) {
                const itemWidth = tagElements[i].offsetWidth + gap;
                if (currentWidth + itemWidth + (i < tags.length - 1 ? styles.moreBadgeReserve : 0) + actionBtnWidth > containerWidth) {
                    break;
                }
                currentWidth += itemWidth;
                count++;
            }
            setVisibleCount(count);
        };

        calculateVisibleTags();
        const observer = new ResizeObserver(calculateVisibleTags);
        if (containerRef.current) {
            observer.observe(containerRef.current);
        }
        return () => observer.disconnect();
    }, [tags, variant, actionButton, styles.moreBadgeReserve]);

    const visibleTags = tags.slice(0, visibleCount);
    const hiddenTags = tags.slice(visibleCount);

    return (
        <TooltipProvider delayDuration={200}>
            <div
                ref={containerRef}
                className={cn(
                    "relative flex min-w-0 flex-1 flex-nowrap items-center overflow-hidden",
                    styles.container,
                )}
            >
                {/* 1. Visible tags */}
                {visibleTags.map((tag, index) => (
                    <div
                        key={tag.id}
                        className={cn(
                            tagClass(tag),
                            "whitespace-nowrap",
                            index === 0 ? styles.tagFirst : 'flex-shrink-0',
                        )}
                    >
                        {renderTagText(tag)}
                    </div>
                ))}

                {/* 2. Overflow "+N" tooltip */}
                {hiddenTags.length > 0 && (
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <div className={styles.moreBadge}>
                                +{hiddenTags.length}
                            </div>
                        </TooltipTrigger>
                        <TooltipContent side="top" noArrow className="bg-white p-2 border border-gray-100 shadow-md">
                            <div className="flex flex-wrap gap-1 max-w-[200px]">
                                {hiddenTags.map((tag) => (
                                    <span key={tag.id} className={cn(tagClass(tag), "whitespace-nowrap")}>
                                        {renderTagText(tag)}
                                    </span>
                                ))}
                            </div>
                        </TooltipContent>
                    </Tooltip>
                )}

                {/* 3. Action button */}
                {actionButton && (
                    <div className="flex-shrink-0 ml-1 flex items-center h-full">
                        {actionButton}
                    </div>
                )}

                {/* 4. Hidden measurement nodes — not part of flex layout */}
                <div className="absolute top-0 left-0 invisible flex -z-10">
                    {tags.map((tag) => (
                        <div key={tag.id} className={cn("tag-measure whitespace-nowrap", styles.measure)}>
                            {renderTagText(tag)}
                        </div>
                    ))}
                </div>
            </div>
        </TooltipProvider>
    );
};

export default TagGroup;
