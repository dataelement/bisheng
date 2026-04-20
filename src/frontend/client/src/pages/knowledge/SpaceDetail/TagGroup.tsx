import React, { useLayoutEffect, useRef, useState, ReactNode } from 'react';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '~/components/ui/Tooltip2';
import { FileTag } from '~/api/knowledge';

const TagGroup = ({ tags, actionButton }: { tags: FileTag[], actionButton?: ReactNode }) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const [visibleCount, setVisibleCount] = useState(1); // 初始默认显示1个

    useLayoutEffect(() => {
        const calculateVisibleTags = () => {
            if (!containerRef.current) return;

            const containerWidth = containerRef.current.offsetWidth;
            // 获取所有用于测量的临时标签元素
            const tagElements = containerRef.current.querySelectorAll('.tag-measure') as NodeListOf<HTMLElement>;
            const moreBadgeWidth = 40; // 预留给 "+N" 的宽度
            const gap = 6; // gap-1.5 (6px)
            const actionBtnWidth = actionButton ? 28 : 0; // button reserved space

            let currentWidth = (tagElements[0]?.offsetWidth || 0) + gap;
            let count = 1;

            // 从第二个标签开始计算
            for (let i = 1; i < tagElements.length; i++) {
                const itemWidth = tagElements[i].offsetWidth + gap;
                // 如果当前总宽 + 这一项 + (若后面还有则预留+N宽) + 按钮保留宽 > 容器总宽
                if (currentWidth + itemWidth + (i < tags.length - 1 ? moreBadgeWidth : 0) + actionBtnWidth > containerWidth) {
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
    }, [tags]);

    const visibleTags = tags.slice(0, visibleCount);
    const hiddenTags = tags.slice(visibleCount);

    return (
        <TooltipProvider delayDuration={200}>
            <div
                ref={containerRef}
                className="relative flex min-h-[24px] min-w-0 flex-1 flex-nowrap items-center gap-1.5 overflow-hidden"
            >
                {/* 1. 实际显示的标签 */}
                {visibleTags.map((tag, index) => (
                    <div
                        key={tag.id}
                        className={`bg-[#f2f3f5] text-[#4e5969] text-xs px-1.5 py-0.5 rounded-sm whitespace-nowrap
              ${index === 0 ? 'min-w-[30px] truncate flex-shrink' : 'flex-shrink-0'}`}
                    >
                        {tag.name}
                    </div>
                ))}

                {/* 2. 折叠后的 +N (使用 Shadcn Tooltip) */}
                {hiddenTags.length > 0 && (
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <div className="bg-[#f2f3f5] text-[#4e5969] font-medium text-xs px-1.5 py-0.5 rounded-sm cursor-pointer flex-shrink-0">
                                +{hiddenTags.length}
                            </div>
                        </TooltipTrigger>
                        <TooltipContent side="top" noArrow className="bg-white p-2 border border-gray-100 shadow-md">
                            <div className="flex flex-wrap gap-1 max-w-[200px]">
                                {hiddenTags.map((tag) => (
                                    <span key={tag.id} className="bg-[#f2f3f5] text-[#4e5969] text-xs px-1.5 py-0.5 rounded-sm">
                                        {tag.name}
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

                {/* 3. 用于测量的隐藏元素 (不参与 Flex 布局) */}
                <div className="absolute top-0 left-0 invisible flex -z-10">
                    {tags.map((tag) => (
                        <div key={tag.id} className="tag-measure px-1.5 py-0.5 text-xs whitespace-nowrap">
                            {tag.name}
                        </div>
                    ))}
                </div>
            </div>
        </TooltipProvider>
    );
};

export default TagGroup;