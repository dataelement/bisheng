"use client"

import { Search, X } from "lucide-react"
import { useRef, useState } from "react"
import { Input } from "~/components/ui"
import { AgentGrid } from "./components/AgentGrid"
import { AgentNavigation } from "./components/AgentNavigation"
import { SearchOverlay } from "./components/SearchOverlay"

export default function AgentCenter() {
    const [searchQuery, setSearchQuery] = useState("")
    const [favorites, setFavorites] = useState<string[]>(["1", "2"]) // Pre-populate with some favorites
    const scrollContainerRef = useRef<HTMLDivElement>(null)
    const sectionRefs = useRef<Record<string, HTMLElement | null>>({})

    const handleCategoryChange = (categoryId: string) => {
        if (searchQuery) {
            setSearchQuery("")
        }

        const targetSection = sectionRefs.current[categoryId]
        if (targetSection && scrollContainerRef.current) {
            const containerTop = scrollContainerRef.current.offsetTop
            const sectionTop = targetSection.offsetTop
            const scrollTop = sectionTop - containerTop - 20 // 20px offset for better visual

            scrollContainerRef.current.scrollTo({
                top: scrollTop,
                behavior: "smooth",
            })
        }
    }

    const handleSearchChange = (query: string) => {
        setSearchQuery(query)
    }

    const handleSearchClear = () => {
        setSearchQuery("")
    }

    const addToFavorites = (agentId: string) => {
        setFavorites((prev) => (prev.includes(agentId) ? prev : [...prev, agentId]))
    }

    const removeFromFavorites = (agentId: string) => {
        setFavorites((prev) => prev.filter((id) => id !== agentId))
    }

    return (
        <div className="min-h-screen bg-background">
            {/* Fixed Header */}
            <div className="sticky top-0 z-40 bg-background">
                <div className="container mx-auto px-6 py-6">
                    <div className="mt-2">
                        <h1 className="text-blue-600 text-[32px] font-medium mb-2">探索BISHENG的智能体</h1>
                        <p className="text-muted-foreground text-base">您可以在这里选择需要的智能体来进行生产与工作～</p>
                    </div>
                    <div className="mt-12 flex items-center justify-between">
                        <AgentNavigation onCategoryChange={handleCategoryChange} />
                        <div className="relative w-80">
                            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-blue-500 w-4 h-4" />
                            <Input
                                type="text"
                                placeholder="搜索您需要的智能体"
                                value={searchQuery}
                                onChange={(e) => handleSearchChange(e.target.value)}
                                className="pl-10 pr-10 h-8"
                            />
                            {searchQuery && (
                                <button
                                    onClick={handleSearchClear}
                                    className="absolute right-3 top-1/2 transform -translate-y-1/2 text-muted-foreground hover:text-foreground"
                                >
                                    <X className="w-4 h-4" />
                                </button>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            {/* Scrollable Content */}
            <div className="relative" style={{ height: "calc(100vh - 200px)" }}>
                <div ref={scrollContainerRef} className="container mx-auto px-6 py-6 pb-96 h-full overflow-y-auto">
                    <AgentGrid
                        favorites={favorites}
                        onAddToFavorites={addToFavorites}
                        onRemoveFromFavorites={removeFromFavorites}
                        sectionRefs={sectionRefs}
                    />
                </div>

                {/* Search Overlay */}
                {searchQuery && (
                    <SearchOverlay
                        query={searchQuery}
                        favorites={favorites}
                        onAddToFavorites={addToFavorites}
                        onClose={handleSearchClear}
                    />
                )}
            </div>
        </div>
    )
}
