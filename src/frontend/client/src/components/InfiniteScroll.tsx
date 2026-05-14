import React, { useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";

interface InfiniteScrollProps {
    children: React.ReactNode;
    loadMore: () => void;
    hasMore: boolean;
    isLoading: boolean;
    className?: string;
    rootMargin?: string;
    emptyText?: string;
}

export function InfiniteScroll({
    children,
    loadMore,
    hasMore,
    isLoading,
    className = "",
    rootMargin = "200px",
    emptyText = "",
}: InfiniteScrollProps) {
    const sentinelRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const observer = new IntersectionObserver(
            (entries) => {
                const entry = entries[0];
                // 触发条件：进入视口 && 还有更多 && 当前没在加载
                if (entry.isIntersecting && hasMore && !isLoading) {
                    loadMore();
                }
            },
            { rootMargin }
        );

        if (sentinelRef.current) {
            observer.observe(sentinelRef.current);
        }

        return () => observer.disconnect();
    }, [hasMore, isLoading, loadMore, rootMargin]);

    return (
        <div className={className}>
            {children}

            {/* 哨兵节点 */}
            <div ref={sentinelRef} className="h-px w-full opacity-0" />

            {/* 底部状态显示 */}
            <div className="py-8 flex justify-center">
                {isLoading && (
                    <div className="flex items-center gap-2 text-[#86909c] text-sm">
                        <Loader2 className="size-4 animate-spin" />
                        正在加载...
                    </div>
                )}
                {!hasMore && !isLoading && (
                    <div className="text-gray-300 text-sm">
                        {emptyText}
                    </div>
                )}
            </div>
        </div>
    );
}