"use client"

import { useState, useEffect, useRef, useCallback, useMemo } from "react"
import { AgentCard } from "./AgentCard"

interface SearchOverlayProps {
    query: string
    results: any[]
    loading: boolean
    favorites: string[]
    onAddToFavorites: (agentId: string) => void
    onRemoveFromFavorites: (agentId: string) => void
    onClose: () => void
}

export function SearchOverlay({ 
    query, 
    results,
    loading,
    favorites, 
    onAddToFavorites, 
    onRemoveFromFavorites,
    onClose 
}: SearchOverlayProps) {
    const [displayedResults, setDisplayedResults] = useState<any[]>([])
    const [isLoadingMore, setIsLoadingMore] = useState(false)
    const [hasMore, setHasMore] = useState(true)
    const scrollContainerRef = useRef<HTMLDivElement>(null)
    const itemsPerLoad = 8

    // 过滤结果
    const filteredResults = useMemo(() => {
        return results.filter((agent: any) =>
            agent.name.toLowerCase().includes(query.toLowerCase()) ||
            agent.description.toLowerCase().includes(query.toLowerCase())
        )
    }, [results, query])

    const loadMoreItems = useCallback(() => {
        if (isLoadingMore || !hasMore) return

        setIsLoadingMore(true)

        // 使用requestAnimationFrame确保在下一帧执行
        requestAnimationFrame(() => {
            const currentLength = displayedResults.length
            const nextItems = filteredResults.slice(currentLength, currentLength + itemsPerLoad)
            
            setDisplayedResults((prev) => [...prev, ...nextItems])
            setHasMore(currentLength + nextItems.length < filteredResults.length)
            setIsLoadingMore(false)
        })
    }, [displayedResults.length, filteredResults, isLoadingMore, hasMore, itemsPerLoad])

    // 重置显示结果
    useEffect(() => {
        const initialItems = filteredResults.slice(0, itemsPerLoad)
        setDisplayedResults(initialItems)
        setHasMore(initialItems.length < filteredResults.length)
    }, [filteredResults, itemsPerLoad])

    // 滚动事件处理 - 使用防抖优化性能
    const handleScroll = useCallback(() => {
        const container = scrollContainerRef.current
        if (!container || isLoadingMore || !hasMore) return

        const { scrollTop, scrollHeight, clientHeight } = container
        const threshold = 50 // 减小阈值，更容易触发加载
        
        // 添加调试信息
        console.log("Scroll check:", {
            scrollTop,
            scrollHeight,
            clientHeight,
            threshold: scrollHeight - scrollTop - clientHeight,
            hasMore,
            isLoadingMore
        })

        if (scrollHeight - scrollTop - clientHeight < threshold) {
            console.log("Loading more items...")
            loadMoreItems()
        }
    }, [hasMore, isLoadingMore, loadMoreItems])

    // 添加滚动事件监听 - 使用被动事件监听器提高性能
    useEffect(() => {
        const container = scrollContainerRef.current
        if (!container) return

        container.addEventListener("scroll", handleScroll, { passive: true })
        return () => container.removeEventListener("scroll", handleScroll)
    }, [handleScroll])

    // 初始加载完成后检查是否需要加载更多
    useEffect(() => {
        const container = scrollContainerRef.current
        if (!container || filteredResults.length <= itemsPerLoad) return
        
        // 检查内容是否不足一屏，如果是则自动加载更多
        if (container.scrollHeight <= container.clientHeight && hasMore && !isLoadingMore) {
            console.log("Auto-loading more items due to short content")
            loadMoreItems()
        }
    }, [filteredResults, hasMore, isLoadingMore, loadMoreItems, itemsPerLoad])

    return (
        <div className="absolute inset-0 bg-background/95 backdrop-blur-sm z-50">
            <div ref={scrollContainerRef} className="h-full overflow-auto">
                <div className="container mx-auto px-6 py-6">
                    {loading && displayedResults.length === 0 ? (
                        <div className="text-center py-12">
                            <div className="inline-flex items-center gap-2 text-muted-foreground">
                                <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin"></div>
                                搜索中...
                            </div>
                        </div>
                    ) : displayedResults.length > 0 ? (
                        <>
                            <div className="mb-6">
                                <h2 className="text-xl font-medium mb-2 text-left">
                                    搜索结果 "{query}" ({filteredResults.length} 个结果)
                                </h2>
                            </div>

                            <div className="grid grid-cols-4 gap-2 mb-8">
                                {displayedResults.map((agent) => (
                                    <AgentCard
                                        key={agent.id}
                                        agent={{
                                            id: agent.id.toString(),
                                            name: agent.name,
                                            description: agent.description || "暂无描述",
                                            icon: "🤖",
                                            category: "search"
                                        }}
                                        isFavorite={favorites.includes(agent.id.toString())}
                                        showRemove={false}
                                        onAddToFavorites={() => onAddToFavorites(agent.id.toString())}
                                        onRemoveFromFavorites={() => onRemoveFromFavorites(agent.id.toString())}
                                    />
                                ))}
                            </div>

                            {isLoadingMore && (
                                <div className="text-center py-8">
                                    <div className="inline-flex items-center gap-2 text-muted-foreground">
                                        <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin"></div>
                                        加载更多...
                                    </div>
                                </div>
                            )}

                            {!hasMore && displayedResults.length > 0 && (
                                <div className="text-center py-8">
                                    <p className="text-muted-foreground">已显示全部结果</p>
                                </div>
                            )}
                        </>
                    ) : (
                        <div className="text-center py-12">
                            <p className="text-muted-foreground">未找到相关智能体</p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}