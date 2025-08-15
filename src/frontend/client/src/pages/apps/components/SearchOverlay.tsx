"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { AgentCard } from "./AgentCard"

// Mock search results
const mockSearchResults = [
    {
        id: "s1",
        name: "智能搜索助手",
        description: "基于先进的搜索算法，帮助您快速找到所需信息。",
        icon: "🔍",
        category: "search",
    },
    { id: "s2", name: "文档搜索", description: "专业的文档搜索工具，支持多种文件格式。", icon: "📄", category: "search" },
    { id: "s3", name: "代码搜索", description: "为开发者提供的代码搜索和分析工具。", icon: "💻", category: "search" },
    { id: "s4", name: "图片搜索", description: "智能图片搜索和识别服务。", icon: "🖼️", category: "search" },
    { id: "s5", name: "语音搜索", description: "支持语音输入的智能搜索助手。", icon: "🎤", category: "search" },
    { id: "s6", name: "视频搜索", description: "专业的视频内容搜索和分析工具。", icon: "🎥", category: "search" },
    { id: "s7", name: "学术搜索", description: "专门用于学术研究的文献搜索工具。", icon: "🎓", category: "search" },
    { id: "s8", name: "商品搜索", description: "电商平台商品搜索和比价工具。", icon: "🛍️", category: "search" },
    { id: "s9", name: "新闻搜索", description: "实时新闻搜索和资讯聚合服务。", icon: "📰", category: "search" },
    { id: "s10", name: "地图搜索", description: "地理位置搜索和导航服务。", icon: "🗺️", category: "search" },
]

interface SearchOverlayProps {
    query: string
    favorites: string[]
    onAddToFavorites: (agentId: string) => void
    onClose: () => void
}

export function SearchOverlay({ query, favorites, onAddToFavorites, onClose }: SearchOverlayProps) {
    const [displayedResults, setDisplayedResults] = useState<typeof mockSearchResults>([])
    const [isLoading, setIsLoading] = useState(false)
    const [hasMore, setHasMore] = useState(true)
    const scrollContainerRef = useRef<HTMLDivElement>(null)
    const itemsPerLoad = 8

    // Filter results based on query
    const filteredResults = mockSearchResults.filter(
        (agent) =>
            agent.name.toLowerCase().includes(query.toLowerCase()) ||
            agent.description.toLowerCase().includes(query.toLowerCase()),
    )

    const loadMoreItems = useCallback(() => {
        if (isLoading || !hasMore) return

        setIsLoading(true)

        // Simulate loading delay
        setTimeout(() => {
            const currentLength = displayedResults.length
            const nextItems = filteredResults.slice(currentLength, currentLength + itemsPerLoad)

            setDisplayedResults((prev) => [...prev, ...nextItems])
            setHasMore(currentLength + nextItems.length < filteredResults.length)
            setIsLoading(false)
        }, 300)
    }, [displayedResults.length, filteredResults, isLoading, hasMore])

    useEffect(() => {
        const initialItems = filteredResults.slice(0, itemsPerLoad)
        setDisplayedResults(initialItems)
        setHasMore(initialItems.length < filteredResults.length)
    }, [query])

    const handleScroll = useCallback(() => {
        const container = scrollContainerRef.current
        if (!container) return

        const { scrollTop, scrollHeight, clientHeight } = container
        const threshold = 100 // Load more when 100px from bottom

        if (scrollHeight - scrollTop - clientHeight < threshold && hasMore && !isLoading) {
            loadMoreItems()
        }
    }, [hasMore, isLoading, loadMoreItems])

    useEffect(() => {
        const container = scrollContainerRef.current
        if (!container) return

        container.addEventListener("scroll", handleScroll)
        return () => container.removeEventListener("scroll", handleScroll)
    }, [handleScroll])

    return (
        <div className="absolute inset-0 bg-background/95 backdrop-blur-sm z-50">
            <div ref={scrollContainerRef} className="h-full overflow-auto">
                <div className="container mx-auto px-6 py-6">
                    {/* <div className="mb-6">
                        <h2 className="text-xl font-medium mb-2 text-left">
                            搜索结果 "{query}" ({filteredResults.length} 个结果)
                        </h2>
                    </div> */}

                    {displayedResults.length > 0 ? (
                        <>
                            <div className="grid grid-cols-4 gap-2 mb-8">
                                {displayedResults.map((agent) => (
                                    <AgentCard
                                        key={agent.id}
                                        agent={agent}
                                        isFavorite={favorites.includes(agent.id)}
                                        showRemove={false}
                                        onAddToFavorites={() => onAddToFavorites(agent.id)}
                                        onRemoveFromFavorites={() => { }}
                                    />
                                ))}
                            </div>

                            {isLoading && (
                                <div className="text-center py-8">
                                    <div className="inline-flex items-center gap-2 text-muted-foreground">
                                        <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin"></div>
                                        加载中...
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
